#pragma once

inline unsigned *getResultPtr() {
  unsigned *resData = nullptr;
  asm volatile("la %0, _test_resdata" : "=r"(resData));
  return resData;
}
