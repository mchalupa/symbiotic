#!/bin/sh

if [  "x$UPDATE" = "x1" -o -z "$(ls -A $SRCDIR/klee)" ]; then
	git_submodule_init
fi

mkdir -p klee/build-${LLVM_VERSION}
pushd klee/build-${LLVM_VERSION}

# Our version of KLEE does not work with STP now
# STP_FLAGS=
# if [ "$BUILD_STP" = "yes" -o -d $ABS_SRCDIR/stp ]; then
# 	STP_FLAGS="-DENABLE_SOLVER_STP=ON -DSTP_DIR=${ABS_SRCDIR}/stp"
# fi
STP_FLAGS="-DENABLE_SOLVER_STP=OFF"

Z3_FLAGS=
if [ "$HAVE_Z3" = "yes" -o "$BUILD_Z3" = "yes" ]; then
	Z3_FLAGS=-DENABLE_SOLVER_Z3=ON
	if [ -d ${ABS_SRCDIR}/z3 ]; then
		Z3_FLAGS="$Z3_FLAGS -DCMAKE_LIBRARY_PATH=${ABS_SRCDIR}/z3/build/"
		Z3_FLAGS="$Z3_FLAGS -DCMAKE_INCLUDE_PATH=${ABS_SRCDIR}/z3/src/api"
	fi
else
	exitmsg "KLEE needs Z3 library"
fi

if [ ! -d CMakeFiles ]; then
	# use our zlib, if we compiled it
	ZLIB_FLAGS=
	if [ -d $ABS_RUNDIR/zlib ]; then
		ZLIB_FLAGS="-DZLIB_LIBRARY=-L${PREFIX}/lib;-lz"
		ZLIB_FLAGS="$ZLIB_FLAGS -DZLIB_INCLUDE_DIR=$PREFIX/include"
	fi

	if which lit &>/dev/null; then
		HAVE_LIT=on
	else
		HAVE_LIT=off
	fi

	EXTRA_FLAGS=""
	if [ -d $ABS_SRCDIR/googletest ]; then
		HAVE_GTEST="yes"
		EXTRA_FLAGS="-DGTEST_SRC_DIR=$ABS_SRCDIR/googletest"
	fi

	if [ "$HAVE_LIT"="yes" -a "$HAVE_GTEST" = "yes" ]; then
		ENABLE_TESTS="on"
	else
		ENABLE_TESTS="off"
	fi
	
	case "$BUILD_TYPE" in
		"Release" | "Debug")
			KLEE_RUNTIME_BUILD_TYPE="$BUILD_TYPE"
			;;
		"MinSizeRel")
			KLEE_RUNTIME_BUILD_TYPE="Release"
			;;
		"RelWithDebInfo")
			KLEE_RUNTIME_BUILD_TYPE="Release+Debug"
			;;
		*)
			exitmsg "Unknown CMake build type!"
			;;
	esac

	cmake .. -DCMAKE_INSTALL_PREFIX=$LLVM_PREFIX \
		-DCMAKE_BUILD_TYPE=${BUILD_TYPE}\
		-DKLEE_RUNTIME_BUILD_TYPE=${KLEE_RUNTIME_BUILD_TYPE} \
		-DLLVM_CONFIG_BINARY=$(abspath ${LLVM_CONFIG}) \
		-DENABLE_UNIT_TESTS=${ENABLE_TESTS} \
		-DENABLE_SYSTEM_TESTS=${ENABLE_TESTS} \
		-DENABLE_TCMALLOC=${ENABLE_TCMALLOC} \
		$ZLIB_FLAGS $Z3_FLAGS $STP_FLAGS ${EXTRA_FLAGS}\
		|| clean_and_exit 1 "git"
fi

if [ "$UPDATE" = "1" ]; then
	git fetch --all
	git checkout $KLEE_BRANCH
	git pull
fi

# build 32-bit and 64-bit libs and install them to prefix
(build && make install) || exit 1

mv $LLVM_PREFIX/lib64/klee $LLVM_PREFIX/lib/klee || true
rmdir $LLVM_PREFIX/lib64 || true

# move 32-bit library version to correct prefix
mkdir -p $LLVM_PREFIX/lib32/klee/runtime
mv $LLVM_PREFIX/lib/klee/runtime/*32*.bc* \
	$LLVM_PREFIX/lib32/klee/runtime/ || exit 1

popd

