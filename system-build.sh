#!/bin/bash
#
# Build Symbiotic from scratch and setup environment for
# development if needed. Try using only system libraries.
#
#  (c) Marek Chalupa, 2016 - 2020
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.

set -e

PHASE="doing initialization"

source "$(dirname $0)/scripts/build-utils.sh"

RUNDIR=`pwd`
SRCDIR=`dirname $0`
ABS_RUNDIR=`abspath $RUNDIR`
ABS_SRCDIR=`abspath $SRCDIR`


usage()
{
	echo "$0 [archive | full-archive] [update] [slicer | scripts | klee | witness | bin] OPTS"
	echo "" # new line
	echo -e "build-type=TYPE    - set Release/Debug build"
	echo -e "llvm-config        - use the given llvm-config binary"
	echo -e "archive            - create a zip file with symbiotic"
	echo -e "full-archive       - create a zip file with symbiotic and add non-standard dependencies"
	echo -e "update             - update repositories"
	echo "" # new line
	echo -e "slicer, scripts,"
	echo -e "klee, witness"
	echo -e "bin     - run compilation _from_ this point"
	echo "" # new line
	echo -e "OPTS = options for make (i. e. -j8)"
}

export PREFIX=${PREFIX:-`pwd`/install}
export LD_LIBRARY_PATH="$PREFIX/lib:$LD_LIBRARY_PATH"
export C_INCLUDE_PATH="$PREFIX/include:$C_INCLUDE_PATH"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig:$PREFIX/share/pkgconfig:$PKG_CONFIG_PATH"

FROM='0'
UPDATE=
OPTS=

ARCHIVE="no"
FULL_ARCHIVE="no"
BUILD_KLEE="yes"
BUILD_PREDATOR="no"
BUILD_LLVM2C='yes'
LLVM_CONFIG=

while [ $# -gt 0 ]; do
	case $1 in
		'help'|'--help')
			usage
			exit 0
		;;
		'slicer')
			FROM='1'
		;;
		'klee')
			FROM='4'
		;;
		'witness')
			FROM='5'
		;;
		'scripts')
			FROM='6'
		;;
		'bin')
			FROM='7'
		;;
		'no-klee')
			BUILD_KLEE=no
		;;
		'no-llvm2c')
			BUILD_LLVM2C="no"
		;;
		'update')
			UPDATE=1
		;;
		build-predator)
			BUILD_PREDATOR="yes"
		;;

		llvm-config=*)
			LLVM_CONFIG=${1##*=}
		;;
		archive)
			ARCHIVE="yes"
		;;
		full-archive)
			ARCHIVE="yes"
			FULL_ARCHIVE="yes"
		;;
		build-type=*)
			BUILD_TYPE=${1##*=}
		;;
		*)
			if [ -z "$OPTS" ]; then
				OPTS="$1"
			else
				OPTS="$OPTS $1"
			fi
		;;
	esac
	shift
done

if [ "x$OPTS" = "x" ]; then
	OPTS='-j1'
fi

PHASE="checking system"

HAVE_32_BIT_LIBS=$(if check_32_bit; then echo "yes"; else echo "no"; fi)
HAVE_Z3=$(if check_z3; then echo "yes"; else echo "no"; fi)
HAVE_GTEST=$(if check_gtest; then echo "yes"; else echo "no"; fi)
ENABLE_TCMALLOC=$(if check_tcmalloc; then echo "on"; else echo "off"; fi)

if [ "$HAVE_32_BIT_LIBS" = "no" -a "$BUILD_KLEE" = "yes" ]; then
	exitmsg "KLEE needs 32-bit libc headers to build 32-bit versions of runtime libraries. On Ubuntu, this is the package libc6-dev-i386 (or gcc-multilib), on Fedora-based systems it is glibc-devel.i686."
fi

# Try to get the previous build type if no is given
if [ -z "$BUILD_TYPE" ]; then
	if [ -f "CMakeCache.txt" ]; then
		BUILD_TYPE=$(cat CMakeCache.txt | grep CMAKE_BUILD_TYPE | cut -f 2 -d '=')
	fi

	# no build type means Release
	[ -z "$BUILD_TYPE" ] && BUILD_TYPE="Release"

	echo "Previous build type identified as $BUILD_TYPE"
fi

if [ "$BUILD_TYPE" != "Debug" -a \
     "$BUILD_TYPE" != "Release" -a \
     "$BUILD_TYPE" != "RelWithDebInfo" -a \
     "$BUILD_TYPE" != "MinSizeRel" ]; then
	exitmsg "Invalid type of build: $BUILD_TYPE";
fi

# create prefix directory
mkdir -p $PREFIX/bin
mkdir -p $PREFIX/lib
mkdir -p $PREFIX/lib32
mkdir -p $PREFIX/include

check()
{
	MISSING=""
	if ! which true ; then
		echo "Need 'which' command."
		MISSING="which"
	fi

	if [ "$BUILD_KLEE" = "yes" ]; then
		if ! which unzip &>/dev/null; then
			echo "Need 'unzip' utility"
			MISSING="unzip $MISSING"
		fi
	fi

	if ! cmake --version &>/dev/null; then
		echo "cmake is needed"
		MISSING="cmake $MISSING"
	fi

	if ! make --version &>/dev/null; then
		echo "make is needed"
		MISSING="make $MISSING"
	fi

	if ! rsync --version &>/dev/null; then
		# TODO: fix the bootstrap script to use also cp
		echo "sbt-instrumentation needs rsync when bootstrapping json. "
		MISSING="rsync $MISSING"
	fi

	if ! tar --version &>/dev/null; then
		echo "Need tar utility"
		MISSING="tar $MISSING"
	fi

	if ! xz --version &>/dev/null; then
		echo "Need xz utility"
		MISSING="xz $MISSING"
	fi

	if [ "$MISSING" != "" ]; then
		exitmsg "Missing dependencies: $MISSING"
	fi

	if [ "$BUILD_KLEE" = "yes" -a "$HAVE_Z3" = "no" ]; then
		exitmsg "KLEE needs Z3"
	fi
}


# check if we have everything we need
check

######################################################################
#   LLVM
#     Copy the LLVM libraries
######################################################################
PHASE="setting up LLVM"

test -z "$LLVM_CONFIG" && LLVM_CONFIG=$(which llvm-config || true)

if [ ! -z $LLVM_CONFIG -a -x $LLVM_CONFIG ]; then
	echo "Using llvm-config: $LLVM_CONFIG";
else
	exitmsg "Cannot find llvm-config binary. Try using llvm-config= switch"
fi

# LLVM tools that we need
LLVM_VERSION=$($LLVM_CONFIG --version)
LLVM_VERSION=${LLVM_VERSION%git}

LLVM_TOOLS="opt clang llvm-link llvm-dis llvm-nm"
export LLVM_PREFIX="$PREFIX/llvm-$LLVM_VERSION"

LLVM_MAJOR_VERSION="${LLVM_VERSION%%\.*}"
LLVM_MINOR_VERSION=${LLVM_VERSION#*\.}
LLVM_MINOR_VERSION="${LLVM_MINOR_VERSION%\.*}"

LLVM_BIN_DIR=$("$LLVM_CONFIG" --bindir)
LLVM_LIB_DIR=$("$LLVM_CONFIG" --libdir)

# LLVM 4.0+ -> $(llvm-config --cmakedir)
# LLVM 3.9  -> $(llvm-config --libdir)/cmake/llvm
# older     -> Fedora/RHEL + Git build: $(llvm-config --prefix)/share/llvm/cmake
#              Debian based: /usr/share/llvm-x.y/cmake
#              Other: TODO
LLVM_DIR=$("$LLVM_CONFIG" --cmakedir 2> /dev/null || true)
if [ -z "$LLVM_DIR" ]; then
	if [ "$LLVM_MAJOR_VERSION" -eq 3 -a "$LLVM_MINOR_VERSION" -eq 9 ]; then
		LLVM_DIR="$LLVM_LIB_DIR/cmake/llvm"
	else
		echo "LLVM 3.8 and lower do not have a uniform location of LLVMConfig.cmake."
		echo "If this fails, please, file an issue."
		echo "Trying some defaults:"

		# Git + Fedora/RHEL
		LLVM_DIR="$("$LLVM_CONFIG" --prefix)/share/llvm/cmake"
		if [ ! -f "$LLVM_DIR/LLVMConfig.cmake" ]; then
			# Debian based
			LLVM_DIR="/usr/share/llvm-$LLVM_MAJOR_VERSION.$LLVM_MINOR_VERSION/cmake"
		fi
	fi

	if [ ! -f "$LLVM_DIR/LLVMConfig.cmake" ]; then
		exitmsg "Cannot find LLVMConfig.cmake file in $LLVM_DIR."
	fi

	if ! grep "$LLVM_VERSION" "$LLVM_DIR/LLVMConfigVersion.cmake" ; then
		exitmsg "llvm-config and LLVMConfig.cmake versions do not match."
	fi
fi

# detect the link type of LLVM that we use
if [ "$($LLVM_CONFIG --shared-mode --libs)" = "shared" ] || \
        # TODO: $LLVM_CONFIG --shared-mode is broken on macOS:
        # https://bugs.llvm.org/show_bug.cgi?id=40252
        # This workaround won't be needed when we switch to CMake.
        stat "$LLVM_LIB_DIR"/libLLVM.dylib; then
    LLVM_DYLIB="on"
else
    LLVM_DYLIB="off"
fi

mkdir -p "$LLVM_PREFIX/bin"
for T in $LLVM_TOOLS; do
	check_llvm_tool "$LLVM_BIN_DIR/$T"

	# copy the binaries only with full-archive option
	if [ "$FULL_ARCHIVE" = "no" ] ; then
		ln -fs "$LLVM_BIN_DIR/$T" "$LLVM_PREFIX/bin"
		continue
	fi

	rm -f "$LLVM_PREFIX/bin/$T"
	cp -L -f "$LLVM_BIN_DIR/$T" "$LLVM_PREFIX/bin"
done

mkdir -p "$LLVM_PREFIX/lib"
CLANG_LIB_DIR="$LLVM_LIB_DIR/clang"
if [ ! -d "$CLANG_LIB_DIR" ]; then
	exitmsg "Invalid path to clang libraries: $CLANG_LIB_DIR"
fi
ln -sf "$CLANG_LIB_DIR" "$LLVM_PREFIX/lib/"

######################################################################
#   dg
######################################################################
PHASE="building dg"
if [ $FROM -le 1 ]; then
	if [  "x$UPDATE" = "x1" -o -z "$(ls -A $SRCDIR/dg)" ]; then
		git_submodule_init
	fi

	# download the dg library
	pushd "$SRCDIR/dg" || exitmsg "Cloning failed"
	mkdir -p build-${LLVM_VERSION} || exitmsg "error"
	pushd build-${LLVM_VERSION} || exitmsg "error"

	if [ ! -d CMakeFiles ]; then
		cmake .. \
			-DCMAKE_BUILD_TYPE=${BUILD_TYPE} \
			-DCMAKE_INSTALL_LIBDIR:PATH=lib \
			-DCMAKE_INSTALL_PREFIX=$LLVM_PREFIX \
			-DCMAKE_INSTALL_RPATH='$ORIGIN/../lib' \
			-DLLVM_LINK_DYLIB="$LLVM_DYLIB" \
			-DLLVM_DIR="$LLVM_DIR" \
			|| clean_and_exit 1 "git"
	fi

	(build && make install) || exitmsg "Failed building DG"
	popd
	popd
fi

if [ "`pwd`" != $ABS_SRCDIR ]; then
	exitmsg "Inconsistency in the build script, should be in $ABS_SRCDIR"
fi

######################################################################
#   sbt-slicer
######################################################################
PHASE="building sbt-slicer"
if [ $FROM -le 1 ]; then

	# initialize instrumentation module if not done yet
	if [  "x$UPDATE" = "x1" -o -z "$(ls -A $SRCDIR/sbt-slicer)" ]; then
		git_submodule_init
	fi

	pushd "$SRCDIR/sbt-slicer" || exitmsg "Cloning failed"
	mkdir -p build-${LLVM_VERSION} || exitmsg "error"
	pushd build-${LLVM_VERSION} || exitmsg "error"
	if [ ! -d CMakeFiles ]; then
		cmake .. \
			-DCMAKE_BUILD_TYPE=${BUILD_TYPE}\
			-DCMAKE_INSTALL_LIBDIR:PATH=lib \
			-DCMAKE_INSTALL_FULL_DATADIR:PATH=$LLVM_PREFIX/share \
			-DLLVM_DIR="$LLVM_DIR" \
			-DDG_PATH=$ABS_SRCDIR/dg \
			-DLLVM_LINK_DYLIB="$LLVM_DYLIB" \
			-DCMAKE_INSTALL_PREFIX=$LLVM_PREFIX \
			-DCMAKE_INSTALL_RPATH='$ORIGIN/../lib' \
			|| clean_and_exit 1 "git"
	fi

	(build && make install) || exitmsg "Failed building sbt-slicer"
	popd
	popd
fi

if [ "`pwd`" != $ABS_SRCDIR ]; then
	exitmsg "Inconsistency in the build script, should be in $ABS_SRCDIR"
fi

######################################################################
#   KLEE
######################################################################
PHASE="building KLEE"
if [ $FROM -le 4  -a "$BUILD_KLEE" = "yes" ]; then
	source scripts/build-klee.sh
fi

if [ "`pwd`" != $ABS_SRCDIR ]; then
	exitmsg "Inconsistency in the build script, should be in $ABS_SRCDIR"
fi

######################################################################
#   Predator
######################################################################
PHASE="building Predator"
if [  -d predator-${LLVM_VERSION} ]; then
	# we already got a build of predator, so rebuild it
	BUILD_PREDATOR="yes"
fi
if [ $FROM -le 6 -a "$BUILD_PREDATOR" = "yes" ]; then
	if [ ! -d predator-${LLVM_VERSION} ]; then
               git_clone_or_pull "https://github.com/staticafi/predator" -b svcomp21-v1 predator-${LLVM_VERSION}
	fi

	pushd predator-${LLVM_VERSION}

	if [ ! -f cl_build/CMakeCache.txt ]; then
		./switch-host-llvm.sh "$LLVM_DIR"
	fi

    build || exitmsg "Failed building Predator"
	mkdir -p $LLVM_PREFIX/predator/lib
	cp sl_build/*.so $LLVM_PREFIX/predator/lib
	cp sl_build/slllvm* $LLVM_PREFIX/bin/
	cp sl_build/*.sh $LLVM_PREFIX/predator/
	cp build-aux/cclib.sh $LLVM_PREFIX/predator/
	cp passes-src/passes_build/*.so $LLVM_PREFIX/predator/lib

	popd
fi

if [ "`pwd`" != $ABS_SRCDIR ]; then
	exitmsg "Inconsistency in the build script, should be in $ABS_SRCDIR"
fi


######################################################################
#   instrumentation
######################################################################
PHASE="building sbt-instrumentation"
if [ $FROM -le 6 ]; then
	# initialize instrumentation module if not done yet
	if [  "x$UPDATE" = "x1" -o -z "$(ls -A $SRCDIR/sbt-instrumentation)" ]; then
		git_submodule_init
	fi

	pushd "$SRCDIR/sbt-instrumentation" || exitmsg "Cloning failed"

	# bootstrap JSON library if needed
	if [ ! -f src/jsoncpp.cpp ]; then
		./bootstrap-json.sh || exitmsg "Failed generating json files"
	fi

	mkdir -p build-${LLVM_VERSION}
	pushd build-${LLVM_VERSION}
	if [ ! -d CMakeFiles ]; then
		cmake .. \
			-DCMAKE_BUILD_TYPE=${BUILD_TYPE}\
			-DCMAKE_INSTALL_LIBDIR:PATH=lib \
			-DCMAKE_INSTALL_FULL_DATADIR:PATH=$LLVM_PREFIX/share \
			-DDG_PATH=$ABS_SRCDIR/dg \
			-DLLVM_DIR="$LLVM_DIR" \
			-DLLVM_LINK_DYLIB="$LLVM_DYLIB" \
			-DCMAKE_INSTALL_PREFIX=$LLVM_PREFIX \
			|| clean_and_exit 1 "git"
	fi

	(build && make install) || exitmsg "Building sbt-instrumentation failed"

	popd
	popd
fi

if [ "`pwd`" != $ABS_SRCDIR ]; then
	exitmsg "Inconsistency in the build script, should be in $ABS_SRCDIR"
fi

######################################################################
#   llvm2c
######################################################################
PHASE="building llvm2c"
if [ $FROM -le 6 -a "$BUILD_LLVM2C" = "yes" ]; then
	source scripts/build-llvm2c.sh
fi

######################################################################
#   transforms (LLVMsbt.so)
######################################################################
PHASE="building LLVMsbt.so"
if [ $FROM -le 6 ]; then

	mkdir -p transforms/build-${LLVM_VERSION}
	pushd transforms/build-${LLVM_VERSION}

	# build prepare and install lib and scripts
	if [ ! -d CMakeFiles ]; then
		cmake .. \
			-DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
			-DCMAKE_INSTALL_PREFIX=$PREFIX \
			-DCMAKE_INSTALL_LIBDIR:PATH=$LLVM_PREFIX/lib \
			-DLLVM_DIR="$LLVM_DIR" \
			|| clean_and_exit 1
	fi

	(build && make install) || clean_and_exit 1
	popd

if [ "`pwd`" != $ABS_SRCDIR ]; then
	exitmsg "Inconsistency in the build script, should be in $ABS_SRCDIR"
fi
fi

######################################################################
#   copy lib and include files
######################################################################
PHASE="installing files and function models"
if [ $FROM -le 6 ]; then
	if [ ! -d CMakeFiles ]; then
		cmake . \
			-DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
			-DCMAKE_INSTALL_PREFIX=$PREFIX \
			-DCMAKE_INSTALL_LIBDIR:PATH=$LLVM_PREFIX/lib \
			|| exitmsg "Failed configuring files installation"
	fi

	(build && make install) || exitmsg "Failed installing files"

	# precompile bitcode files
    #PHASE="precompiling function models"
	#scripts/precompile_bitcode_files.sh

if [ "`pwd`" != $ABS_SRCDIR ]; then
	exitmsg "Inconsistency in the build script, should be in $ABS_SRCDIR"
fi
fi

######################################################################
#  extract versions of components and create the distribution
######################################################################
if [ $FROM -le 7 ]; then
    PHASE="generating versions.py file"
	source scripts/gen-version.sh

    PHASE="creating distribution"
	source scripts/push-to-git.sh
fi

