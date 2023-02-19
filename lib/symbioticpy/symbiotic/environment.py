#!/usr/bin/env python3

from os import environ, getcwd
from os.path import isfile, isdir
from . utils import err, dbg
from . utils.utils import process_grep

import re

def _vers_are_same(v1, v2):
    parts1 = v1.split('.')
    parts2 = v2.split('.')

    # compare major and minor versions, ignore micro version
    return all(parts1[i] == parts2[i] for i in range(2))

def _check_clang_in_path(llvm_version):
    versline = process_grep(['clang', '-v'], 'clang version')
    if versline[0] != 0 or len(versline[1]) != 1:
        return False

    match = re.search(r'\d+\.\d+\.\d+', versline[1][0].decode())
    if match is None:
        err('Could not determine the clang version')

    return _vers_are_same(match[0], llvm_version)

def _set_symbiotic_environ(tool, env, opts):
    env.cwd = getcwd()

    if opts.search_include_paths:
        from . includepaths import IncludePathsSearcher
        additional_include_paths = IncludePathsSearcher().get()
        for p in additional_include_paths:
            env.prepend('C_INCLUDE_DIR', p)

    # check whether we are in distribution directory or in the developement directory
    opts.devel_mode = isfile('{0}/build.sh'.format(env.symbiotic_dir))

    llvm_version = tool.llvm_version()
    llvm_prefix = '{0}/llvm-{1}'.format(env.symbiotic_dir, llvm_version)

    if not isdir(llvm_prefix):
        dbg('Did not find a build of LLVM, checking the system LLVM')
        if not _check_clang_in_path(llvm_version):
            dbg("System's LLVM does not have the right version ({0})".format(llvm_version))
            dbg("Cannot use system LLVM neither the directory with LLVM binaries exists: '{0}'".format(llvm_prefix))

            # last resort -- try whether we have some binaries in the install/ folder
            dbg("Trying binaries in install/ directory")
            llvm_prefix = '{0}/install/llvm-{1}'.format(env.symbiotic_dir, llvm_version)
            env.prepend('PATH', '{0}/bin'.format(llvm_prefix))
            if not _check_clang_in_path(llvm_version):
                err('Could not find a suitable LLVM binaries')
            else:
                dbg('The binary in install/ folder can do!')

        # else we're using the system llvm and we're ok

    env.prepend('C_INCLUDE_DIR', '{0}/include'.format(env.symbiotic_dir))

    if opts.devel_mode:
        env.prepend('PATH', '{0}/scripts'.format(env.symbiotic_dir))
        env.prepend('PATH', '{0}/llvm-{1}/build/bin'.format(env.symbiotic_dir, llvm_version))
        env.prepend('PATH', '{0}/dg/build-{1}/tools'.format(env.symbiotic_dir, llvm_version))
        env.prepend('PATH', '{0}/sbt-slicer/build-{1}/src'.format(env.symbiotic_dir, llvm_version))
        env.prepend('PATH', '{0}/sbt-instrumentation/build-{1}/src'.format(env.symbiotic_dir, llvm_version))
        # predator_wrapper.py
        env.prepend('PATH', '{0}/sbt-instrumentation/analyses'.format(env.symbiotic_dir, llvm_version))
        env.prepend('PATH', '{0}/llvm2c/build-{1}/'.format(env.symbiotic_dir, llvm_version))
        env.prepend('PATH', '{0}/predator-{1}/sl_build/'.format(env.symbiotic_dir, llvm_version))

        env.prepend('LD_LIBRARY_PATH', '{0}/build/lib'.format(llvm_prefix))
        env.prepend('LD_LIBRARY_PATH', '{0}/transforms/build-{1}/'.format(env.symbiotic_dir,llvm_version))
        env.prepend('LD_LIBRARY_PATH', '{0}/dg/build-{1}/lib'.format(env.symbiotic_dir, llvm_version))
        env.prepend('LD_LIBRARY_PATH', '{0}/sbt-instrumentation/build-{1}/analyses'.format(env.symbiotic_dir, llvm_version))
        env.prepend('LD_LIBRARY_PATH', '{0}/predator-{1}/sl_build/'.format(env.symbiotic_dir, llvm_version))
        env.prepend('LD_LIBRARY_PATH', '{0}/predator-{1}/passes-src/passes_build/'.format(env.symbiotic_dir, llvm_version))
        opts.instrumentation_files_path = '{0}/sbt-instrumentation/instrumentations/'.format(env.symbiotic_dir)
    else:
        env.prepend('PATH', '{0}/bin'.format(env.symbiotic_dir))
        env.prepend('PATH', '{0}/llvm-{1}/bin'.format(env.symbiotic_dir, llvm_version))
        env.prepend('LD_LIBRARY_PATH', '{0}/lib'.format(env.symbiotic_dir))
        env.prepend('LD_LIBRARY_PATH', '{0}/lib'.format(llvm_prefix))
        env.prepend('LD_LIBRARY_PATH', '{0}/predator/lib'.format(llvm_prefix))
        opts.instrumentation_files_path = '{0}/share/sbt-instrumentation/'.format(llvm_prefix)
    # FIXME: a hack, move to slowbeast directly
    env.prepend('PATH', '{0}/slowbeast'.format(env.symbiotic_dir, llvm_version))

    # Get include paths again now when we have our clang in the path,
    # so that we have at least includes from our clang's instalation
    # (these has the lowest prefs., so just append them
    if opts.search_include_paths:
        additional_include_paths = IncludePathsSearcher().get()
        for p in additional_include_paths:
            env.append('C_INCLUDE_DIR', p)

    # let the tool set its specific environment
    if hasattr(tool, 'set_environment'):
        tool.set_environment(env, opts)

def _parse_environ_vars(opts):
    """
    Parse environment variables of interest and
    change running options accordingly
    """
    # FIXME: do not store these flags into opts but into environ
    if 'C_INCLUDE_DIR' in environ:
        for p in environ['C_INCLUDE_DIR'].split(':'):
            if p != '':
                opts.CPPFLAGS.append('-I{0}'.format(p))
    if 'CFLAGS' in environ:
        opts.CFLAGS += environ['CFLAGS'].split(' ')
    if 'CPPFLAGS' in environ:
        opts.CPPFLAGS += environ['CPPFLAGS'].split(' ')

class Environment:
    """
    Helper class for setting and maintaining
    evnironment for tools
    """
    def __init__(self, symb_dir):
        # the directory where is symbiotic
        self.symbiotic_dir = symb_dir
        # working directory for symbiotic
        self.working_dir = None
        # the current directory from where we call symbiotic
        self.cwd = None

    def prepend(self, env, what):
        """ Prepend 'what' to environment variable 'env'"""
        if env in environ:
            newenv = '{0}:{1}'.format(what, environ[env])
        else:
            newenv = what

        environ[env] = newenv

    def append(self, env, what):
        """ Append 'what' to environment variable 'env'"""
        if env in environ:
            newenv = '{0}:{1}'.format(environ[env], what)
        else:
            newenv = what

        environ[env] = newenv

    def reset(self, what, to):
        """ Set 'what' to environment variable to'"""
        environ[what] = to


    def set(self, tool, opts):
        _set_symbiotic_environ(tool, self, opts)
        _parse_environ_vars(opts)

