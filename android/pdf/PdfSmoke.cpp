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
        const jchar* chars {env->GetStringChars(value, nullptr)};
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
    std::string result {"must be cleared"};
    const int status {
        ConvertPDF::processFile(string(path), string(mode), page, width, height, result)};
    if (status != 0) {
        if (status != -1 || !result.empty())
            env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),
                          "PDF failure contract");
        return nullptr;
    }
    auto bytes = env->NewByteArray(static_cast<jsize>(result.size()));
    if (bytes != nullptr)
        env->SetByteArrayRegion(bytes, 0, static_cast<jsize>(result.size()),
                                reinterpret_cast<const jbyte*>(result.data()));
    return bytes;
}
#endif
