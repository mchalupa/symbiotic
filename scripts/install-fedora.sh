#!/bin/sh

set -e

PACKAGES="curl wget rsync make cmake unzip tar patch glibc-devel.i686 xz zlib python"

# install clang if there is not suitable compiler
if ! which g++ &>/dev/null; then
	if ! which clang++ &>/dev/null; then
		PACKAGES="$PACKAGES clang"
	fi
fi

INSTALL_Z3="N"
INSTALL_LLVM="N"
INSTALL_SQLITE="N"

# Ask for these as the user may have his/her own build
if ! rpm -qa | grep -q z3-devel; then
	echo "Z3 not found, should I install it? [y/N]"
	read INSTALL_Z3
fi

if ! rpm -qa | grep -q llvm-devel; then
	echo "LLVM not found, should I install it? [y/N]"
	read INSTALL_LLVM
fi
if ! rpm -qa | grep -q libsqlite3-devel; then
	echo "SQLite not found, should I install it? [y/N]"
	read INSTALL_SQLITE
fi

if [ "$INSTALL_Z3" = "y" ]; then
	PACKAGES="$PACKAGES z3-devel"
fi
if [ "$INSTALL_LLVM" = "y" ]; then
	PACKAGES="$PACKAGES llvm-devel llvm-static"
fi
if [ "$INSTALL_SQLITE" = "y" ]; then
	PACKAGES="$PACKAGES libsqlite3-devel"
fi



dnf install $PACKAGES

