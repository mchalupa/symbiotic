#!/usr/bin/python

import os, sys
from . utils import err, dbg, enable_debug
from . exceptions import SymbioticException

def get_versions():
    """ Return a tuple (VERSION, versions, llvm_versions) """ 

    # the numbers must be separated by '-, otherwise it will
    # break the tool-module in benchexec
    VERSION='7.0.0-dev'
    try:
        from . versions import versions, build_types
        from . versions import llvm_version as LLVM_VERSION
    except ImportError:
        versions = {
            'symbiotic' : VERSION
        }
        build_types = {
        }
        LLVM_VERSION='unknown'

    return (VERSION, versions, LLVM_VERSION, build_types)

class SymbioticOptions(object):
    def __init__(self):
        # source codes
        self.sources = []

        self.tool_name = 'klee'
        self.is32bit = False
        self.stats = False
        # generate ll or c as output
        self.generate_ll = False
        self.generate_c = False
        self.cc_mode = False
        self.propertystr = None
        self.property = None
        self.noslice = False
        self.malloc_never_fails = False
        self.explicit_symbolic = False
        self.undef_retval_nosym = False
        self.undefined_are_pure = False
        self.timeout = 0
        self.no_optimize = False
        self.no_verification = False
        self.final_output = None
        self.witness_output = '{0}/witness.graphml'.format(os.getcwd())
        self.testsuite_output = '{0}/test-suite'.format(os.getcwd())
        self.witness_with_source_lines = False
        self.source_is_bc = False
        self.optlevel = ["before-O3", "after-O3"]
        self.slicer_pta = 'fi'
        self.slicing_criterion = '__assert_fail,__VERIFIER_error'
        self.memsafety_config_file = 'config.json'
        self.overflow_config_file = 'config.json'
        self.repeat_slicing = 1
        self.dont_exit_on_error = False
        # folders where to look for models of undefined functions
        self.linkundef = ['target', 'verifier', 'libc', 'posix', 'kernel']
        # these files will be linked unconditionally just after compilation
        self.link_files = []
        # these files are going to be linked before slicing if they are undefined
        # (the rest of undefined functions is linked after slicing)
        self.link_files_before_slicing = ['__VERIFIER_exit', '__VERIFIER_silent_exit']
        # additional parameters that can be passed right
        # to the slicer and symbolic executor
        self.slicer_cmd = ['sbt-slicer']
        self.slicer_params = []
        self.tool_params = []
        # these llvm passes will not be run in the optimization phase
        self.disabled_optimizations = []
        self.CFLAGS = []
        self.CPPFLAGS = []
        self.devel_mode = False
        self.instrumentation_files_path = None
        # instrument tracking the state of the program into the program itself
        self.full_instrumentation = False
        self.nowitness = False
        # try to automatically find paths with common header files
        self.search_include_paths = False
        # flag for checking overflows with clang sanitizer
        self.overflow_with_clang = False
        # replay error path
        self.replay_error = False
        # settings specific for the target, but not the one that are passed on command line
        # (for those, tool_params)
        # These are parsed and used by the tool info object.
        self.target_settings = []

        self.sv_comp = False
        self.test_comp = False

        # These were globals previously, move them into stand-alone argparse
        # parser once we switch to argparse
        self.no_integrity_check = False
        self.dump_env_only = False
        self.dump_env_cmd = False
        self.save_files = False
        self.working_dir_prefix = '/tmp'
        self.unroll_count = 0

def _remove_linkundef(options, what):
    try:
        options.linkundef.remove(what)
    except ValueError:
        pass

def set_svcomp(opts):
    opts.sv_comp = True
    opts.no_integrity_check = True
    opts.malloc_never_fails = True
    opts.explicit_symbolic = True
    opts.search_include_paths = False
    opts.linkundef.append('svcomp')
    opts.CFLAGS.append("-fbracket-depth=-1")

    enable_debug('all')

def set_testcomp(opts):
    opts.test_comp = True
    opts.no_integrity_check = True
    opts.malloc_never_fails = True
    opts.explicit_symbolic = True
    opts.search_include_paths = False
    opts.nowitness = True
    opts.linkundef.append('testcomp')
    opts.CFLAGS.append("-fbracket-depth=-1")

    enable_debug('all')

def print_versions():
    VERSION, versions, LLVM_VERSION, build_types = get_versions()
    print('version: {0}'.format(VERSION))
    print('LLVM version: {0}'.format(LLVM_VERSION))
    for (k, v) in versions.items():
        bt = build_types.get(k)
        print('{0:<20} -> {1}{2}'.format(k, v, ' ({0})'.format(bt) if bt else ''))

# FIXME: move me into a different file, this has nothing to do with options
def print_short_vers():
    VERSION, versions, LLVM_VERSION, build_types = get_versions()
    vers = '{0}-'.format(VERSION)
    # the LLVM version of the default verifier
    vers += 'llvm-{0}-'.format(LLVM_VERSION)
    n = 0
    for (k, v) in versions.items():
        if n > 0:
            vers += '-'
        vers += k + ':' + v[:8]
        n += 1

    if 'Debug' in build_types.values():
        vers += '-DBG'

    print(vers)

def print_shortest_vers():
    VERSION, versions, _, build_types = get_versions()
    vers = '{0}-{1}'.format(VERSION, versions['symbiotic'][:8])

    if 'Debug' in build_types.values():
        vers += '-DBG'

    print(vers)

def translate_flags(output, flags):
    for f in flags:
        if os.path.isfile(f):
            output.append(os.path.abspath(f))
        elif f.startswith("-I"):
            output.append("-I{0}".format(os.path.abspath(f[2:])))
        else:
            output.append(f)

### FIXME: use argparse
def parse_command_line():
    import getopt
    from sys import argv
    options = SymbioticOptions()

    try:
        opts, args = getopt.getopt(argv[1:], '',
                                   ['no-slice', '32', 'prp=', 'no-optimize',
                                    'debug=', 'timeout=', 'version', 'help',
                                    'no-verification', 'output=', 'witness=', 'bc',
                                    'optimize=', 'malloc-never-fails',
                                    'pta=', 'no-link', 'slicing-criterion=',
                                    'cflags=', 'cppflags=', 'link=',
                                    'verifier=','target=',
                                    'no-link-undefined', 'repeat-slicing=',
                                    'slicer-params=', 'slicer-cmd=', 'verifier-params=',
                                    'explicit-symbolic', 'undefined-retval-nosym',
                                    'save-files', 'version-short', 'no-witness',
                                    'witness-with-source-lines', 'dont-exit-on-error',
                                    'undefined-are-pure',
                                    'no-integrity-check', 'dump-env', 'dump-env-cmd',
                                    'memsafety-config-file=', 'overflow-config-file=',
                                    'statistics', 'working-dir-prefix=', 'sv-comp', 'test-comp',
                                    'overflow-with-clang', 'gen-ll', 'gen-c', 'test-suite=',
                                    'search-include-paths', 'replay-error', 'cc',
                                    'unroll=', 'full-instrumentation', 'target-settings='])
                                   # add klee-params
    except getopt.GetoptError as e:
        err('{0}'.format(str(e)))


    for opt, arg in opts:
        if opt == '--help':
            print(usage_msg)
            sys.exit(0)
        elif opt == '--debug':
            enable_debug(arg.split(','))
        elif opt == '--gen-ll':
            options.generate_ll = True
        elif opt == '--gen-c':
            options.generate_c = True
        elif opt == '--cc':
            options.tool_name='cc'
            options.cc_mode = True
            options.no_verification = True
        elif opt == '--verifier' or opt == '--target':
            options.tool_name = arg.lower()
        elif opt == '--version-short':
            print_shortest_vers()
            sys.exit(0)
        elif opt == '--version':
            print_versions()
            sys.exit(0)
        elif opt == '--no-slice':
            dbg('Will not slice')
            options.noslice = True
        elif opt == '--sv-comp':
            dbg('Using SV-COMP settings')
            set_svcomp(options)
        elif opt == '--test-comp':
            dbg('Using TEST-COMP settings')
            set_testcomp(options)
        elif opt == '--no-witness':
            dbg('Will not create a witness')
            options.nowitness = True
        elif opt == '--explicit-symbolic':
            options.explicit_symbolic = True
        elif opt == '--undefined-retval-nosym':
            options.undef_retval_nosym = True
        elif opt == '--no-link-undefined':
            dbg('Will not try to find and link undefined functions')
            options.nolinkundef = True
        elif opt == '--no-link':
            for x in arg.split(','):
                _remove_linkundef(options, x)
        elif opt == '--malloc-never-fails':
            dbg('Assuming malloc and calloc will never fail')
            options.malloc_never_fails = True
        elif opt == '--undefined-are-pure':
            dbg('Assuming that undefined functions are pure')
            options.undefined_are_pure = True
        elif opt == '--no-verification':
            dbg('Will not run verification phase')
            options.no_verification = True
        elif opt == '--overflow-with-clang':
            dbg('Will use clang sanitizer for checking overflows.')
            options.overflow_with_clang = True
        elif opt == '--32':
            dbg('Will use 32-bit environment')
            options.is32bit = True
        elif opt == '--no-optimize':
            dbg('Will not optimize the code')
            options.no_optimize = True
            options.optlevel = []
        elif opt == '--optimize':
            dbg('Optimization levels: ' + arg)
            options.optlevel = arg.split(',')
            for o in options.optlevel:
                o = o.strip()
                if o == "none":
                    options.no_optimize = True
                    options.optlevel = []
                    break
        elif opt == '--prp':
            if arg == 'valid-free' or arg == 'valid-deref' or arg == 'valid-memtrack':
                print("WARNING: Separated memsafety properties are not supported "\
                      "at this moment setting the property to \'memsafety\'")
                arg = "memsafety"
            if options.propertystr is not None:
                print("WARNING: only one property is supported at the moment, "\
                      "Symbiotic will use the last one specified")
            options.propertystr = arg
        elif opt == '--pta':
            options.slicer_pta = arg
            if not arg in ['fs', 'fi', 'inv']:
                err('Points-to analysis can be one of: fs, fi, inv')

            dbg('Points-to: {0}'.format(arg))
        elif opt == '--slicing-criterion':
            options.slicing_criterion = arg
            dbg('Slicing criterion: {0}'.format(arg))
        elif opt == '--repeat-slicing':
            try:
                options.repeat_slicing = int(arg)
            except ValueError:
                err('Invalid argument for --repeat-slicing')
            dbg('Will repeat slicing {0} times'.format(arg))
        elif opt == '--timeout':
            try:
                options.timeout = int(arg)
            except ValueError:
                err('Invalid numerical argument for timeout: {0}'.format(arg))
            dbg('Timeout set to {0} sec'.format(arg))
        elif opt == '--output':
            options.final_output = os.path.abspath(arg)
            dbg('Output will be stored to {0}'.format(arg))
        elif opt == '--witness':
            options.witness_output = os.path.expanduser(arg)
            options.witness_output = os.path.abspath(options.witness_output)
            dbg('Witness will be stored to {0}'.format(arg))
        elif opt == '--bc':
            options.source_is_bc = True
            dbg('Given code is bytecode')
        elif opt == '--cflags':
            translate_flags(options.CFLAGS, arg.split())
        elif opt == '--cppflags':
            translate_flags(options.CPPFLAGS, arg.split())
        elif opt == '--slicer-params':
            options.slicer_params = arg.split()
        elif opt == '--slicer-cmd':
            options.slicer_cmd = arg.split()
        elif opt == '--verifier-params':
            options.tool_params = arg.split()
        elif opt == '--target-settings':
            options.target_settings = arg.split()
        elif opt == '--link':
            options.link_files += arg.split(',')
        elif opt == '--save-files':
            options.save_files = True
            options.generate_ll = True
        elif opt == '--working-dir-prefix':
            wdr = os.path.abspath(arg)
            if not os.path.isdir(wdr):
                # we should check also for writebility
                err("'{0}' is not valid prefix for working directory".format(arg))
            options.working_dir_prefix = wdr
        elif opt == '--witness-with-source-lines':
            options.witness_with_source_lines = True
        elif opt == '--dont-exit-on-error':
            options.dont_exit_on_error = True
        elif opt == '--statistics':
            options.stats = True
        elif opt == '--memsafety-config-file':
            options.memsafety_config_file = arg
        elif opt == '--overflow-config-file':
            options.overflow_config_file = arg
        elif opt == '--dump-env':
            options.dump_env_only = True
        elif opt == '--replay-error':
            options.replay_error = True
        elif opt == '--dump-env-cmd':
            options.dump_env_only = True
            options.dump_env_cmd = True
        elif opt == '--search-include-paths':
            options.search_include_paths = True
        elif opt == '--no-integrity-check':
            options.no_integrity_check = True
        elif opt == '--unroll':
            options.unroll_count = int(arg)
        elif opt == '--full-instrumentation':
            options.full_instrumentation = True
        elif opt == '--test-suite':
            options.testsuite_output = os.path.abspath(arg)

    return options, args




usage_msg = """
Usage: symbiotic OPTS sources

where OPTS can be following:

    --bc                      Given file is a bytecode
    --32                      Use 32-bit environment
    --timeout=t               Set timeout to t seconds
    --no-slice                Do not slice the code
    --verifier=name           Use the tool 'name'. Default is KLEE, other tools that
                              can be integrated are Ceagle, CPAchecker, Seahorn,
                              Skink and SMACK.
    --explicit-symbolic       Do not make all memory symbolic,
                              but rely on calls to __VERIFIER_nondet_*
    --undefined-retval-nosym  Do not make return value of undefined functions symbolic,
                              but replace it with 0.
    --malloc-never-fails      Suppose malloc and calloc never return NULL
    --undefined-are-pure      Suppose that undefined functions have no side-effects
    --no-verification         Do not run verification phase (handy for debugging)
    --optimize=opt1,...       Run optimizations, every item in the optimizations list
                              is a string of type when-level, where when is 'before'
                              or 'after' (slicing) and level in 'conservative', 'klee',
                              'O2, 'O3'. A special value is 'none', which
                              disables optimizations (same as --no-optimize).
                              You can also pass optimizations directly to LLVM's opt,
                              by providing a string when-opt-what, e.g. before-opt-iconstprop
    --no-optimize             Don't optimize the code (same as --optimize=none)
    --libc=klee               Link klee-libc.bc to the module
    --slicing-criterion=C     Slice to slicing criterion (function call-sites) 'C'
                              (default is '__assert_fail')
    --repeat-slicing=N        Repeat slicing N times
    --prp=property            Specify property that should hold. It is either LTL formula
                              as specivied by SV-COMP, or one of following shortcuts:
                                null-deref      -- program is free of null-dereferences
                                valid-deref     -- all dereferences are valid
                                valid-free      -- all free() calls are valid
                                valid-memtrack  -- all memory is freed
                                memsafety       -- valid-deref + valid-free
                                                   + valid-memtrack
                                undefined-behavior -- check for undefined behaviour
                                  or undef-behavior
                                signed-overflow -- check for signed integer overflow
                              The string can be given on line or in a file.
    --memsafety-config-file   Set the configuration file for memsafety. The files
                              can be found in share/sbt-instrumentation/memsafety/
    --overflow-config-file    Set the configuration file for overflows. The files
                              can be found in share/sbt-instrumentation/int_overflows/
    --overflow-with-clang     Do not instrument checks for signed integer overflows with
                              sbt-instrumentation, use clang sanitizer instead.
    --pta=[fs|fi|old]         Use flow-sensitive/flow-insensitive or old
                              (flow-insensitive too) points-to analysis when slicing.
                              Default is the old
    --debug=what              Print debug messages, what can be comma separated list of:
                              all, compile, slicer
                              In that case you get verbose output. You can just use
                              --debug= to print basic messages.
    --generate-ll             Generate also .ll files (for debugging)
    --output=FILE             Store the final code (that is to be run by a tool) to FILE
    --witness=FILE            Store witness into FILE (default is witness.graphml)
    --witness-with-source-lines
                              Store source lines into the witness (may have memory overhead).
    --cflags=flags
    --cppflags=flags          Append extra CFLAGS and CPPFLAGS to use while compiling,
                              the environment CFLAGS and CPPFLAGS are used too
    --slicer-params=STR       Pass parameters directly to slicer
    --slicer-cmd=STR          Command to run slicer, default: sbt-slicer
    --verifier-params=STR     Pass parameters directly to the verifier
    --save-files              Do not remove working files after running.
                              The files will be stored in the symbiotic_files directory.
    --no-link                 Do not link missing functions from the given category
                              (libc, svcomp, verifier, posix, kernel). The argument
                              is a comma-separated list of values.
    --no-witness              Do not create a witness
    --dont-exit-on-error      Do not exit when the property violation is reached,
                              but continue searching
    --help                    Show help message
    --version                 Return version
    --version-short           Return version as one-line string
    --no-integrity-check      Does not run integrity check. For development only.
    --dump-env                Only dump environment variables (for debugging)
    --dump-env-cmd            Dump environment variables for using them in command line
    --statistics              Dump statistics about bitcode
    --working-dir-prefix      Where to create the temporary directory (defaults to /tmp)
    --replay-error            Try replaying a found error on non-sliced code
    --search-include-paths    Try automatically finding paths with standard include directories
    --sv-comp                 Shortcut for SV-COMP settings (malloc-never-fails, etc.)
    --test-comp               Shortcut for TEST-COMP settings
    --test-suit               Output for tests if --test-comp options is on
    --full-instrumentation    Tranform checking errors to reachability problem, i.e.
                              instrument tracking of the state of the program directly
                              into the program.

    One (and only one) of the sources must contain 'main' function
"""

