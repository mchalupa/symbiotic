//                     The LLVM Compiler Infrastructure
//
// This file is distributed under the University of Illinois Open Source
// License. See LICENSE.TXT for details.

#include <vector>

#include "llvm/IR/DataLayout.h"
#include "llvm/IR/BasicBlock.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/GlobalVariable.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Module.h"
#include "llvm/Pass.h"
#include "llvm/IR/Type.h"
#if LLVM_VERSION_MAJOR >= 4 || (LLVM_VERSION_MAJOR == 3 && LLVM_VERSION_MINOR >= 5)
  #include "llvm/IR/InstIterator.h"
#else
  #include "llvm/Support/InstIterator.h"
#endif
#include "llvm/Support/raw_ostream.h"
#include "llvm/Transforms/Utils/BasicBlockUtils.h"

using namespace llvm;

class RemoveInfiniteLoops : public FunctionPass {
  public:
    static char ID;

    RemoveInfiniteLoops() : FunctionPass(ID) {}

    virtual bool runOnFunction(Function &F);
};

static RegisterPass<RemoveInfiniteLoops> RIL("remove-infinite-loops",
                                             "delete patterns like LABEL: goto LABEL"
                                             "and replace them with exit(0)");
char RemoveInfiniteLoops::ID;

void CloneMetadata(const llvm::Instruction *i1, llvm::Instruction *i2);

bool RemoveInfiniteLoops::runOnFunction(Function &F) {
  Module *M = F.getParent();

  std::vector<BasicBlock *> to_process;
  for (BasicBlock& block : F) {
    // if this is a block that jumps on itself (it has the only instruction
    // which is the jump)
    if (block.size() == 1) {
        auto succ = block.getUniqueSuccessor();
        if (!succ)
            continue;
        // empty block with self-loop
        if (succ == &block)
            to_process.push_back(&block);

        // two empty blocks mutually calling themselves
        if (succ->size() == 1 && succ->getUniqueSuccessor() == &block)
            to_process.push_back(&block);
    }
  }

  if (to_process.empty())
    return false;

  CallInst* ext;
  LLVMContext& Ctx = M->getContext();
  Type *argTy = Type::getInt32Ty(Ctx);
  auto C = M->getOrInsertFunction("__VERIFIER_silent_exit",
                                  Type::getVoidTy(Ctx),
                                  argTy
#if LLVM_VERSION_MAJOR < 5
                                  , nullptr
#endif
                                  );
#if LLVM_VERSION_MAJOR >= 9
  auto extF = cast<Function>(C.getCallee());
#else
  auto extF = cast<Function>(C);
#endif

  std::vector<Value *> args = { ConstantInt::get(argTy, 0) };

  for (BasicBlock *block : to_process) {
    Instruction *T = block->getTerminator();
    ext = CallInst::Create(extF, args);
    CloneMetadata(&*(block->begin()), ext);
    ext->insertBefore(T);

    // replace the jump with unreachable, since exit will terminate
    // the computation
    new UnreachableInst(Ctx, T);
    T->eraseFromParent();
  }

  llvm::errs() << "Removed infinite loop in " << F.getName().data() << "\n";
  return true;
}

