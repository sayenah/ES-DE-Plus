//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  PdfSmoke.cpp
//
//  Written for ES-DE-Plus. Debug instrumentation of the production converter boundary.
//

#if defined(__ANDROID__) && !defined(NDEBUG)
#include "ConvertPDF.h"
#include <jni.h>
#include <utf8.h>

extern "C" JNIEXPORT jbyteArray JNICALL Java_org_esdeplus_frontend_PdfSmoke_nativeProcess(
    JNIEnv* env, jclass, jstring path, jstring mode, jint page, jint width, jint height)
{
    auto string = [env](jstring value) {
        const jsize length {env->GetStringLength(value)};
        if (env->ExceptionCheck())
            return std::string {};
        const jchar* chars {env->GetStringChars(value, nullptr)};
        if (env->ExceptionCheck())
            return std::string {};
        std::string converted;
        if (chars != nullptr) {
            try {
                utf8::utf16to8(chars, chars + length, std::back_inserter(converted));
            }
            catch (const std::exception&) {
            }
            env->ReleaseStringChars(value, chars);
        }
        return converted;
    };
    const std::string filename {string(path)};
    if (env->ExceptionCheck())
        return nullptr;
    const std::string option {string(mode)};
    if (env->ExceptionCheck())
        return nullptr;
    std::string result {"must be cleared"};
    const int status {ConvertPDF::processFile(filename, option, page, width, height, result)};
    if (status != 0) {
        if (status != -1 || !result.empty()) {
            jclass exception {env->FindClass("java/lang/IllegalStateException")};
            if (env->ExceptionCheck() || exception == nullptr)
                return nullptr;
            env->ThrowNew(exception, "PDF failure contract");
        }
        return nullptr;
    }
    auto bytes = env->NewByteArray(static_cast<jsize>(result.size()));
    if (env->ExceptionCheck() || bytes == nullptr)
        return nullptr;
    env->SetByteArrayRegion(bytes, 0, static_cast<jsize>(result.size()),
                            reinterpret_cast<const jbyte*>(result.data()));
    if (env->ExceptionCheck())
        return nullptr;
    return bytes;
}
#endif
