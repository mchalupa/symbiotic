#!/usr/bin/python

import os
import sys
import re

from . options import SymbioticOptions
from . utils import err, dbg, enable_debug, print_elapsed_time, restart_counting_time
from . utils.process import ProcessRunner
from . utils.watch import ProcessWatch, DbgWatch
from . utils.utils import print_stdout, print_stderr, get_symbiotic_dir
from . exceptions import SymbioticException


class PrepareWatch(ProcessWatch):
    def __init__(self, lines=100):
        ProcessWatch.__init__(self, lines)

    def parse(self, line):
        if b'Removed' in line or b'Defining' in line:
            sys.stdout.write(line.decode('utf-8'))
        else:
            dbg(line.decode('utf-8'), 'prepare', False)


class SlicerWatch(ProcessWatch):
    def __init__(self, lines=100):
        ProcessWatch.__init__(self, lines)

    def parse(self, line):
        if b'INFO' in line:
            dbg(line.decode('utf-8'), domain='slicer', print_nl=False)
        elif b'ERROR' in line or b'error' in line:
            print_stderr(line.decode('utf-8'))
        else:
            dbg(line.decode('utf-8'), 'slicer', False)


class InstrumentationWatch(ProcessWatch):
    def __init__(self, lines=100):
        ProcessWatch.__init__(self, lines)

    def parse(self, line):
        if b'Info' in line:
            dbg(line.decode('utf-8'), domain='instrumentation', print_nl=False)
        elif b'ERROR' in line or b'error' in line:
            print_stderr(line.decode('utf-8'))
        elif b'Inserted' in line:
            print_stdout(line.decode('utf-8'), print_nl=False)
        else:
            dbg(line.decode('utf-8'), 'slicer', False)


class PrintWatch(ProcessWatch):
    def __init__(self, prefix='', color=None):
        ProcessWatch.__init__(self)
        self._prefix = prefix
        self._color = color

    def parse(self, line):
        print_stdout(line.decode('utf-8'), prefix=self._prefix,
                     print_nl=False, color=self._color)


class CompileWatch(ProcessWatch):
    """ Parse output of compilation """

    def __init__(self):
        ProcessWatch.__init__(self)

    def parse(self, line):
        if b'error:' in line:
            print_stderr('cc: {0}'.format(line.decode('utf-8')), color='BROWN')
        else:
            dbg(line.decode('utf-8'), 'compile', print_nl=False)


class UnsuppWatch(ProcessWatch):
    unsupported_call = re.compile('.*call to .* is unsupported.*')

    def __init__(self):
        ProcessWatch.__init__(self)
        self._ok = True

    def ok(self):
        return self._ok

    def parse(self, line):
        uline = line.decode('utf-8')
        dbg(uline, domain='prepare', print_nl=False)
        self._ok = not UnsuppWatch.unsupported_call.match(uline)


class ToolWatch(ProcessWatch):
    def __init__(self, tool):
        # store the whole output of a tool
        ProcessWatch.__init__(self, None)
        self._tool = tool

    def parse(self, line):
        if b'ERROR' in line or b'WARN' in line or b'Assertion' in line\
           or b'error' in line or b'warn' in line:
            sys.stderr.write(line.decode('utf-8'))
        else:
            dbg(line.decode('utf-8'), 'all', False)


def report_results(res):
    dbg(res)
    color = 'BROWN'

    if res.startswith('false'):
        color = 'RED'
        print_stdout('Error found.', color=color)
    elif res == 'true':
        color = 'GREEN'
        print_stdout('No error found.', color=color)
    elif res.startswith('error') or\
            res.startswith('ERROR'):
        color = 'RED'
        print_stdout('Failure!', color=color)

    sys.stdout.flush()
    print_stdout('RESULT: ', print_nl=False)
    print_stdout(res, color=color)
    sys.stdout.flush()

    return res


def get_optlist_before(optlevel):
    from . optimizations import optimizations
    lst = []
    for opt in optlevel:
        if not opt.startswith('before-'):
            continue

        o = opt[7:]
        if o.startswith('opt-'):
            lst.append(o[3:])
        else:
            if o in optimizations:
                lst += optimizations[o]

    return lst


def get_optlist_after(optlevel):
    from . optimizations import optimizations
    lst = []
    for opt in optlevel:
        if not opt.startswith('after-'):
            continue

        o = opt[6:]
        if o.startswith('opt-'):
            lst.append(o[3:])
        else:
            if o in optimizations:
                lst += optimizations[o]

    return lst


class Symbiotic(object):
    """
    Instance of symbiotic tool. Instruments, prepares, compiles and runs
    symbolic execution on given source(s)
    """

    def __init__(self, tool, src, opts=None, symb_dir=None):
        # source file
        self.sources = src
        # source compiled to llvm bytecode
        self.llvmfile = None
        # the file that will be used for symbolic execution
        self.runfile = None
        # currently running process
        self.current_process = None
        # the directory that symbiotic script is located
        if symb_dir:
            self.symbiotic_dir = symb_dir
        else:
            self.symbiotic_dir = get_symbiotic_dir()

        if opts is None:
            self.options = SymbioticOptions(self.symbiotic_dir)
        else:
            self.options = opts

        # definitions of our functions that we linked
        self._linked_functions = []

        # tool to use
        self._tool = tool

    def _run(self, cmd, watch, err_msg):
        self.current_process = ProcessRunner(cmd, watch)
        if self.current_process.run() != 0:
            self.current_process.printOutput(sys.stderr, 'RED')
            self.current_process = None
            raise SymbioticException(err_msg)

        self.current_process = None

    def _compile_to_llvm(self, source, output=None, with_g=True, opts=[]):
        """
        Compile given source to LLVM bytecode
        """

        cmd = ['clang', '-c', '-emit-llvm', '-include', 'symbiotic.h'] + opts

        if with_g:
            cmd.append('-g')

        if self.options.CFLAGS:
            cmd += self.options.CFLAGS
        if self.options.CPPFLAGS:
            cmd += self.options.CPPFLAGS

        if self.options.is32bit:
            cmd.append('-m32')

        cmd.append('-o')
        if output is None:
            llvmfile = '{0}.bc'.format(source[:source.rfind('.')])
        else:
            llvmfile = output

        cmd.append(llvmfile)
        cmd.append(source)

        self._run(cmd, CompileWatch(),
                  "Compiling source '{0}' failed".format(source))

        return llvmfile

    def run_opt(self, passes):
        self._run_opt(passes)

    def _run_opt(self, passes):
        output = '{0}-pr.bc'.format(self.llvmfile[:self.llvmfile.rfind('.')])
        cmd = ['opt', '-load', 'LLVMsvc15.so',
               self.llvmfile, '-o', output] + passes

        self._run(cmd, PrepareWatch(), 'Prepare phase failed')
        self.llvmfile = output

    def _get_stats(self, prefix=''):
        cmd = ['opt', '-load', 'LLVMsvc15.so', '-count-instr',
               '-o', '/dev/null', self.llvmfile]
        try:
            self._run(cmd, PrintWatch('INFO: ' + prefix), 'Failed running opt')
        except SymbioticException:
            # not fatal, continue working
            dbg('Failed getting statistics')

    def _instrument(self, prp):
        llvm_dir = 'llvm-{0}'.format(self._tool.llvm_version())
        if self.options.is32bit:
            libdir = os.path.join(self.symbiotic_dir, llvm_dir, 'lib32')
        else:
            libdir = os.path.join(self.symbiotic_dir, llvm_dir, 'lib')

        prefix = os.path.join(self.symbiotic_dir, llvm_dir,
                              'share/sbt-instrumentation/')

        tolinkbc = None
        if prp == 'MEMSAFETY':
            # default config file is 'config.json'
            config_file = self.options.memsafety_config_file
            config = prefix + 'memsafety/' + config_file
            # check wether we have this file precompiled
            # (this may be a distribution where we're trying to
            # avoid compilation of anything else than sources)
            precompiled_bc = '{0}/memsafety.bc'.format(libdir)
            if os.path.isfile(precompiled_bc):
                tolinkbc = precompiled_bc
            else:
                tolink = prefix + 'memsafety/memsafety.c'
        elif prp == 'NULL-DEREF':
            config = prefix + 'null_deref/config.json'
            precompiled_bc = '{0}/null_deref.bc'.format(libdir)
            if os.path.isfile(precompiled_bc):
                tolinkbc = precompiled_bc
            else:
                tolink = prefix + 'null_deref/null_deref.c'
        else:
            raise SymbioticException('BUG: Unhandled property')

        # module with defintions of instrumented functions
        if not tolinkbc:
            tolinkbc = self._compile_to_llvm(tolink, with_g=False, opts=['-O2'])

        self._get_stats('Before instrumentation ')

        output = '{0}-inst.bc'.format(self.llvmfile[:self.llvmfile.rfind('.')])
        cmd = ['sbt-instr', config, self.llvmfile, tolinkbc, output]
        self._run(cmd, InstrumentationWatch(), 'Instrumenting the code failed')

        self.llvmfile = output
        self._get_stats('After instrumentation ')

        # once we instrumented the code, we can link the definitions
        # of functions
        self.link(libs=[tolinkbc])
        self._get_stats('After instrumentation and linking ')

    def instrument(self):
        """
        Instrument the code.
        """

        # FIXME: do not compare the strings all the time...

        if 'MEMSAFETY' in self.options.prp:
            self._instrument('MEMSAFETY')
        elif 'MEM-TRACK' in self.options.prp and\
             'VALID-DEREF' in self.options.prp and\
             'VALID-FREE' in self.options.prp:
            self._instrument('MEMSAFETY')
        else:
            # these two are mutually exclusive
            if 'MEM-TRACK' in self.options.prp:
                self._instrument('MEM-TRACK')
            elif 'VALID-FREE' in self.options.prp:
                self._instrument('VALID-FREE')

            if 'VALID-DEREF' in self.options.prp:
                self._instrument('VALID-DEREF')

            if 'NULL-DEREF' in self.options.prp:
                self._instrument('NULL-DEREF')

    def _get_libraries(self, which=[]):
        files = []
        if self.options.add_libc:
            d = '{0}/lib'.format(self.symbiotic_dir)
            if self.options.is32bit:
                d += '32'

            files.append('{0}/klee/runtime/klee-libc.bc'.format(d))

        return files

    def link(self, output=None, libs=None):
        if libs is None:
            libs = self._get_libraries()

        if not libs:
            return

        if output is None:
            output = '{0}-ln.bc'.format(
                self.llvmfile[:self.llvmfile.rfind('.')])

        cmd = ['llvm-link', '-o', output] + libs
        if self.llvmfile:
            cmd.append(self.llvmfile)

        self._run(cmd, DbgWatch('compile'),
                  'Failed linking llvm file with libraries')
        self.llvmfile = output

    def _link_undefined(self, undefs):
        tolink = []
        for ty in self.options.linkundef:
            for undef in undefs:
                name = '{0}/lib/{1}/{2}.c'.format(
                    self.symbiotic_dir, ty, undef)
                if os.path.isfile(name):
                    output = os.path.join(os.getcwd(), os.path.basename(name))
                    output = '{0}.bc'.format(output[:output.rfind('.')])
                    self._compile_to_llvm(name, output)
                    tolink.append(output)

                    # for debugging
                    self._linked_functions.append(undef)

        if tolink:
            self.link(libs=tolink)
            return True

        return False

    def link_unconditional(self):
        """ Link the files that we got on the command line """

        return self._link_undefined(self.options.link_files)

    def _get_undefined(self, bitcode):
        cmd = ['llvm-nm', '-undefined-only', '-just-symbol-name', bitcode]
        watch = ProcessWatch(None)
        self._run(cmd, watch, 'Failed getting undefined symbols from bitcode')
        return map(lambda s: s.strip(), watch.getLines())

    def link_undefined(self, only_func=[]):
        if not self.options.linkundef:
            return

        # get undefined functions from the bitcode
        undefs = self._get_undefined(self.llvmfile)
        if only_func:
            undefs = filter(set(only_func).__contains__, undefs)

        # --------------------- # python3 compatibility
        if self._link_undefined([x.decode('ascii') for x in undefs]):
            # if we linked someting, try get undefined again,
            # because the functions may have added some new undefined
            # functions
            if only_func is None:
                self.link_undefined()

    def slicer(self, criterion, add_params=[]):
        output = '{0}.sliced'.format(self.llvmfile[:self.llvmfile.rfind('.')])
        cmd = ['sbt-slicer', '-c', criterion]
        if self.options.slicer_pta in ['fi', 'fs']:
            cmd.append('-pta')
            cmd.append(self.options.slicer_pta)

        # we do that now using _get_stats
        # cmd.append('-statistics')

        if self.options.undefined_are_pure:
            cmd.append('-undefined-are-pure')

        if self.options.slicer_params:
            cmd += self.options.slicer_params

        if add_params:
            cmd += add_params

        cmd.append(self.llvmfile)

        self._run(cmd, SlicerWatch(), 'Slicing failed')
        self.llvmfile = output

    def optimize(self, passes, disable=[]):
        if self.options.no_optimize:
            return

        disable += self.options.disabled_optimizations
        if disable:
            ds = set(disable)
            passes = filter(lambda x: not ds.__contains__(x), passes)

        output = '{0}-opt.bc'.format(self.llvmfile[:self.llvmfile.rfind('.')])
        cmd = ['opt', '-o', output, self.llvmfile]
        cmd += passes

        self._run(cmd, CompileWatch(), 'Optimizing the code failed')
        self.llvmfile = output

    def check_llvmfile(self, llvmfile, check='-check-unsupported'):
        """
        Check whether the bitcode does not contain anything
        that we do not support
        """
        cmd = ['opt', '-load', 'LLVMsvc15.so', check,
               '-o', '/dev/null', llvmfile]
        try:
            self._run(cmd, UnsuppWatch(), 'Failed checking the code')
        except SymbioticException:
            return False

        return True

    def preprocess_llvm(self):
        """
        Run a command that proprocesses a llvm code
        for a particular tool
        """
        cmd, output = self._tool.preprocess_llvm(self.llvmfile)
        if not cmd:
            return

        self._run(cmd, DbgWatch('compile'),
                  'Failed preprocessing the llvm code')
        self.llvmfile = output

    def run_verification(self):
        cmd = self._tool.cmdline(self._tool.executable(),
                                 self.options.tool_params, [self.llvmfile],
                                 self.options.prpfile, [])

        returncode = 0
        watch = ToolWatch(self._tool)
        try:
            self._run(cmd, watch, 'Running the verifier failed')
        except SymbioticException as e:
            print_stderr(str(e), color='RED')
            returncode = 1

        return self._tool.determine_result(returncode, 0,
                                           watch.getLines(), False)

    def terminate(self):
        if self.current_process:
            self.current_process.terminate()

    def kill(self):
        if self.current_process:
            self.current_process.kill()

    def kill_wait(self):
        if self.current_process and self.current_process.exitStatus() is None:
            from time import sleep
            while self.current_process.exitStatus() is None:
                self.current_process.kill()

                print('Waiting for the child process to terminate')
                sleep(0.5)

            print('Killed the child process')

    def run(self):
        try:
            return self._run_symbiotic()
        except KeyboardInterrupt:
            self.terminate()
            self.kill()
            print('Interrupted...')

    def _compile_sources(self):
        llvmsrc = []
        for source in self.sources:
            opts = ['-Wno-unused-parameter', '-Wno-unused-attribute',
                    '-Wno-unused-label', '-Wno-unknown-pragmas']
            if 'UNDEF-BEHAVIOR' in self.options.prp:
                opts.append('-fsanitize=undefined')
                opts.append('-fno-sanitize=unsigned-integer-overflow')
            elif 'SIGNED-OVERFLOW' in self.options.prp:
                opts.append('-fsanitize=signed-integer-overflow')
                opts.append('-fsanitize=shift')
                # XXX: remove once we have better CD algorithm
                self.options.disabled_optimizations = ['-instcombine']

            llvms = self._compile_to_llvm(source, opts=opts)
            llvmsrc.append(llvms)

        # link all compiled sources to a one bytecode
        # the result is stored to self.llvmfile
        self.link('code.bc', llvmsrc)

    def perform_slicing(self):
        # run optimizations that can make slicing more precise
        opt = get_optlist_before(self.options.optlevel)
        if opt:
            self.optimize(passes=opt)

        # break the infinite loops just before slicing
        # so that the optimizations won't make them syntactically infinite again
        # self.run_opt(['-reg2mem', '-break-infinite-loops', '-remove-infinite-loops',
        self.run_opt(['-break-infinite-loops', '-remove-infinite-loops',
                      # this somehow break the bitcode
                      #'-mem2reg'
                      ])

        self._get_stats('Before slicing ')

        # print info about time
        print_elapsed_time('INFO: Compilation, preparation and '
                           'instrumentation time', color='WHITE')

        for n in range(0, self.options.repeat_slicing):
            dbg('Slicing the code for the {0}. time'.format(n + 1))
            add_params = []
            # if n == 0 and self.options.repeat_slicing > 1:
            #    add_params = ['-pta-field-sensitive=8']

            self.slicer(self.options.slicing_criterion, add_params)

            if self.options.repeat_slicing > 1:
                opt = get_optlist_after(self.options.optlevel)
                if opt:
                    self.optimize(passes=opt)
                    self.run_opt(['-break-infinite-loops',
                                  '-remove-infinite-loops'])

        print_elapsed_time('INFO: Total slicing time', color='WHITE')

        self._get_stats('After slicing ')

    def _run_symbiotic(self):
        restart_counting_time()

        # disable these optimizations, since LLVM 3.7 does
        # not have them
        self.options.disabled_optimizations = ['-aa', '-demanded-bits',  # not in 3.7
                                               '-globals-aa', '-forceattrs',  # not in 3.7
                                               '-inferattrs', '-rpo-functionattrs',  # not in 3.7
                                               '-tti', '-bdce', '-elim-avail-extern',  # not in 3.6
                                               '-float2int', '-loop-accesses'  # not in 3.6
                                               ]

        # compile all sources if the file is not given
        # as a .bc file
        if self.options.source_is_bc:
            self.llvmfile = self.sources[0]
        else:
            self._compile_sources()

        self._get_stats('After compilation ')

        if not self.check_llvmfile(self.llvmfile, '-check-concurr'):
            print(
                'Unsupported call (probably pthread API or floating point stdlib functions)')
            return report_results('unknown')

        self._run_opt(['-rename-verifier-funs',
                       '-rename-verifier-funs-source={0}'.format(self.sources[0])])

        # link the files that we got on the command line
        # and that we are required to link in on any circumstances
        self.link_unconditional()

        # remove definitions of __VERIFIER_* that are not created by us
        # and syntactically infinite loops
        # we use functionattrs pass to set NoRecurse flag for functions
        # because of instrumentation with pointer analysis
        passes = ['-prepare', '-remove-infinite-loops', '-functionattrs']

        memsafety = 'VALID-DEREF' in self.options.prp or \
                    'VALID-FREE' in self.options.prp or \
                    'VALID-MEMTRACK' in self.options.prp or \
                    'MEMSAFETY' in self.options.prp
        if memsafety:
            # remove error calls, we'll put there our own
            passes.append('-remove-error-calls')
        elif 'UNDEF-BEHAVIOR' in self.options.prp or\
             'SIGNED-OVERFLOW' in self.options.prp:
            # remove the original calls to __VERIFIER_error and put there
            # new on places where the code exhibits an undefined behavior
            passes += ['-remove-error-calls', '-replace-ubsan']

        self.run_opt(passes=passes)

        # we want to link these functions before instrumentation,
        # because in those we need to check for invalid dereferences
        if memsafety:
            self.link_undefined()
            self.link_undefined()

        # now instrument the code according to properties
        self.instrument()

        passes = self._tool.prepare()
        # make all memory symbolic (if desired)
        # and then delete undefined function calls
        # and replace them by symbolic stuff
        if not self.options.explicit_symbolic:
            passes.append('-initialize-uninitialized')
        if passes:
            self.run_opt(passes)

        # link with the rest of libraries if needed (klee-libc)
        self.link()

        # link undefined (no-op when prepare is turned off)
        # (this still can have an effect even in memsafety, since we
        # can link __VERIFIER_malloc0.c or similar)
        self.link_undefined()

        # slice the code
        if not self.options.noslice:
            self.perform_slicing()
        else:
            print_elapsed_time('INFO: Compilation, preparation and '
                               'instrumentation time', color='WHITE')

        # for the memsafety property, make functions behave like they have
        # side-effects, because LLVM instrumentations could remove them otherwise,
        # even though they contain calls to assert
        if memsafety:
            self.run_opt(['-remove-readonly-attr'])

        # start a new time era
        restart_counting_time()

        # optimize the code after slicing and
        # before verification
        opt = get_optlist_after(self.options.optlevel)
        if opt:
            self.optimize(passes=opt)

        # FIXME: make this KLEE specific
        if not self.check_llvmfile(self.llvmfile):
            dbg('Unsupported call (probably floating handling)')
            return report_results('unsupported call')

        # there may have been created new loops
        passes = ['-remove-infinite-loops']

        # instrument our malloc -- either the version that can fail,
        # or the version that can not fail.
        if self.options.malloc_never_fails:
            passes += ['-instrument-alloc-nf']
        else:
            passes += ['-instrument-alloc']

        # remove/replace the rest of undefined functions
        # for which we do not have a definition and
        # that has not been removed
        if self.options.undef_retval_nosym:
            passes += ['-delete-undefined-nosym']
        else:
            passes += ['-delete-undefined']

        passes += self._tool.prepare_after()
        self.run_opt(passes)

        # delete-undefined may insert __VERIFIER_make_symbolic
        # and also other funs like __errno_location may be included
        self.options.linkundef.append('verifier')
        self.link_undefined()

        if self._linked_functions:
            print('Linked our definitions to these undefined functions:')
            for f in self._linked_functions:
                print_stdout('  ', print_nl=False)
                print_stdout(f)

        # XXX: we could optimize the code again here...
        print_elapsed_time('INFO: After-slicing optimizations and preparation time',
                           color='WHITE')

        # tool's specific preprocessing steps
        self.preprocess_llvm()

        if not self.options.final_output is None:
            # copy the file to final_output
            try:
                os.rename(self.llvmfile, self.options.final_output)
                self.llvmfile = self.options.final_output
            except OSError as e:
                msg = 'Cannot create {0}: {1}'.format(
                    self.options.final_output, e.message)
                raise SymbioticException(msg)

        if not self.options.no_verification:
            self._get_stats('Before verification ')
            print_stdout('INFO: Starting verification', color='WHITE')
            found = self.run_verification()
        else:
            found = 'Did not run verification'

        return report_results(found)
