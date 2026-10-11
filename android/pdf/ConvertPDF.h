//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  ConvertPDF.h
//
//  Written for ES-DE-Plus from D-008 and the MIT PDF viewer call surface.
//

#ifndef ES_DE_PLUS_ANDROID_CONVERT_PDF_H
#define ES_DE_PLUS_ANDROID_CONVERT_PDF_H

#if defined(__ANDROID__)
#include <string>

class ConvertPDF
{
public:
    __attribute__((visibility("default"))) static int processFile(const std::string path,
                                                                  const std::string mode,
                                                                  int pageNum,
                                                                  int width,
                                                                  int height,
                                                                  std::string& result);
};
#endif

#endif // ES_DE_PLUS_ANDROID_CONVERT_PDF_H
