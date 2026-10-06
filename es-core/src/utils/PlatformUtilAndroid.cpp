//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  PlatformUtilAndroid.cpp
//
//  Clean-room Android platform bridge implemented against the public ES-DE C++ callers and
//  public Android/SDL APIs.
//

#include "utils/PlatformUtilAndroid.h"

#if defined(__ANDROID__)

#include "Log.h"
#include "utils/FileSystemUtil.h"

#include <SDL2/SDL_system.h>
#include <jni.h>

#include <array>

namespace AndroidVariables
{
    bool sHold {false};
    bool sIsHomeApp {false};
    bool sResetTouchOverlay {false};

    std::string sExternalDataDirectory;
    std::string sInternalDataDirectory;
    std::string sROMDirectory;
}

namespace
{
    struct ActivityContext {
        JNIEnv* env {nullptr};
        jobject activity {nullptr};
        jclass activityClass {nullptr};

        ActivityContext()
        {
            env = static_cast<JNIEnv*>(SDL_AndroidGetJNIEnv());
            if (env == nullptr)
                return;

            activity = SDL_AndroidGetActivity();
            if (activity == nullptr)
                return;

            activityClass = env->GetObjectClass(activity);
        }

        ~ActivityContext()
        {
            if (env != nullptr && activityClass != nullptr)
                env->DeleteLocalRef(activityClass);
        }

        explicit operator bool() const
        {
            return env != nullptr && activity != nullptr && activityClass != nullptr;
        }
    };

    void clearJavaException(JNIEnv* env, const char* method)
    {
        if (env == nullptr || !env->ExceptionCheck())
            return;

        LOG(LogError) << "Android bridge: Java exception while calling " << method;
        env->ExceptionDescribe();
        env->ExceptionClear();
    }

    jmethodID getMethod(ActivityContext& context,
                        const char* method,
                        const char* signature)
    {
        if (!context)
            return nullptr;

        jmethodID id {context.env->GetMethodID(context.activityClass, method, signature)};
        if (id == nullptr)
            clearJavaException(context.env, method);
        return id;
    }

    jstring toJString(JNIEnv* env, const std::string& value)
    {
        return env->NewStringUTF(value.c_str());
    }

    std::string fromJString(JNIEnv* env, jstring value)
    {
        if (env == nullptr || value == nullptr)
            return {};

        const char* chars {env->GetStringUTFChars(value, nullptr)};
        if (chars == nullptr)
            return {};

        std::string result {chars};
        env->ReleaseStringUTFChars(value, chars);
        return result;
    }

    jobjectArray toStringArray(JNIEnv* env, const std::vector<std::string>& values)
    {
        jclass stringClass {env->FindClass("java/lang/String")};
        if (stringClass == nullptr)
            return nullptr;

        jobjectArray array {
            env->NewObjectArray(static_cast<jsize>(values.size()), stringClass, nullptr)};

        for (size_t i {0}; i < values.size(); ++i) {
            jstring value {toJString(env, values[i])};
            env->SetObjectArrayElement(array, static_cast<jsize>(i), value);
            env->DeleteLocalRef(value);
        }

        env->DeleteLocalRef(stringClass);
        return array;
    }

    jobjectArray toStringArray(JNIEnv* env, const std::map<std::string, std::string>& values)
    {
        std::vector<std::string> flattened;
        flattened.reserve(values.size() * 2);
        for (const auto& entry : values) {
            flattened.emplace_back(entry.first);
            flattened.emplace_back(entry.second);
        }
        return toStringArray(env, flattened);
    }

    bool callBool(const char* method, bool fallback = false)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()Z")};
        if (id == nullptr)
            return fallback;

        const jboolean result {context.env->CallBooleanMethod(context.activity, id)};
        clearJavaException(context.env, method);
        return result == JNI_TRUE;
    }

    bool callBool(const char* method, const std::string& arg, bool fallback = false)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "(Ljava/lang/String;)Z")};
        if (id == nullptr)
            return fallback;

        jstring value {toJString(context.env, arg)};
        const jboolean result {context.env->CallBooleanMethod(context.activity, id, value)};
        context.env->DeleteLocalRef(value);
        clearJavaException(context.env, method);
        return result == JNI_TRUE;
    }

    int callInt(const char* method, int fallback = 0)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()I")};
        if (id == nullptr)
            return fallback;

        const jint result {context.env->CallIntMethod(context.activity, id)};
        clearJavaException(context.env, method);
        return static_cast<int>(result);
    }

    int callInt(const char* method,
                const std::string& first,
                const std::string& second,
                int fallback)
    {
        ActivityContext context;
        jmethodID id {
            getMethod(context, method, "(Ljava/lang/String;Ljava/lang/String;)I")};
        if (id == nullptr)
            return fallback;

        jstring firstValue {toJString(context.env, first)};
        jstring secondValue {toJString(context.env, second)};
        const jint result {
            context.env->CallIntMethod(context.activity, id, firstValue, secondValue)};
        context.env->DeleteLocalRef(firstValue);
        context.env->DeleteLocalRef(secondValue);
        clearJavaException(context.env, method);
        return static_cast<int>(result);
    }

    std::string callString(const char* method)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()Ljava/lang/String;")};
        if (id == nullptr)
            return {};

        jstring value {
            static_cast<jstring>(context.env->CallObjectMethod(context.activity, id))};
        clearJavaException(context.env, method);

        std::string result {fromJString(context.env, value)};
        if (value != nullptr)
            context.env->DeleteLocalRef(value);
        return result;
    }

    std::pair<int, int> callIntPair(const char* method,
                                    const std::pair<int, int>& fallback)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()[I")};
        if (id == nullptr)
            return fallback;

        jintArray values {
            static_cast<jintArray>(context.env->CallObjectMethod(context.activity, id))};
        clearJavaException(context.env, method);
        if (values == nullptr || context.env->GetArrayLength(values) < 2) {
            if (values != nullptr)
                context.env->DeleteLocalRef(values);
            return fallback;
        }

        std::array<jint, 2> result {};
        context.env->GetIntArrayRegion(values, 0, 2, result.data());
        context.env->DeleteLocalRef(values);
        return {static_cast<int>(result[0]), static_cast<int>(result[1])};
    }

    void callVoid(const char* method)
    {
        ActivityContext context;
        jmethodID id {getMethod(context, method, "()V")};
        if (id == nullptr)
            return;

        context.env->CallVoidMethod(context.activity, id);
        clearJavaException(context.env, method);
    }
} // namespace

namespace Utils
{
    namespace Platform
    {
        namespace Android
        {
            bool checkConfigurationNeeded()
            {
                return callBool("checkConfigurationNeeded", true);
            }

            bool checkEmulatorInstalled(const std::string& packageName,
                                        const std::string& activityName)
            {
                ActivityContext context;
                jmethodID id {getMethod(
                    context, "checkEmulatorInstalled",
                    "(Ljava/lang/String;Ljava/lang/String;)Z")};
                if (id == nullptr)
                    return false;

                jstring packageValue {toJString(context.env, packageName)};
                jstring activityValue {toJString(context.env, activityName)};
                const jboolean result {context.env->CallBooleanMethod(
                    context.activity, id, packageValue, activityValue)};
                context.env->DeleteLocalRef(packageValue);
                context.env->DeleteLocalRef(activityValue);
                clearJavaException(context.env, "checkEmulatorInstalled");
                return result == JNI_TRUE;
            }

            bool checkNeedResourceCopy(const std::string& buildIdentifier)
            {
                return callBool("checkNeedResourceCopy", buildIdentifier, true);
            }

            int checkRACoreInstalled(const std::string& packageName,
                                     const std::string& coreFile)
            {
                return callInt("checkRACoreInstalled", packageName, coreFile, -2);
            }

            std::pair<int, int> getBatteryStatus()
            {
                return callIntPair("getBatteryStatus", {-1, -1});
            }

            int getBluetoothStatus()
            {
                return callInt("getBluetoothStatus");
            }

            int getCellularStatus()
            {
                return callInt("getCellularStatus");
            }

            bool getCreateSystemDirectories()
            {
                return callBool("getCreateSystemDirectories");
            }

            std::string getExternalDirectory()
            {
                return callString("getExternalDirectory");
            }

            void getInstalledApps(std::vector<std::pair<std::string, std::string>>& appList,
                                  bool gamesOnly,
                                  bool includeMedia)
            {
                appList.clear();

                ActivityContext context;
                jmethodID id {
                    getMethod(context, "getInstalledApps", "(ZZ)[Ljava/lang/String;")};
                if (id == nullptr)
                    return;

                jobjectArray values {static_cast<jobjectArray>(context.env->CallObjectMethod(
                    context.activity, id, gamesOnly ? JNI_TRUE : JNI_FALSE,
                    includeMedia ? JNI_TRUE : JNI_FALSE))};
                clearJavaException(context.env, "getInstalledApps");

                if (values == nullptr)
                    return;

                const jsize size {context.env->GetArrayLength(values)};
                for (jsize i {0}; i + 1 < size; i += 2) {
                    jstring displayName {
                        static_cast<jstring>(context.env->GetObjectArrayElement(values, i))};
                    jstring packageName {
                        static_cast<jstring>(context.env->GetObjectArrayElement(values, i + 1))};

                    appList.emplace_back(fromJString(context.env, displayName),
                                         fromJString(context.env, packageName));

                    if (displayName != nullptr)
                        context.env->DeleteLocalRef(displayName);
                    if (packageName != nullptr)
                        context.env->DeleteLocalRef(packageName);
                }

                context.env->DeleteLocalRef(values);
            }

            std::string getInternalDirectory()
            {
                return callString("getInternalDirectory");
            }

            int getWifiStatus()
            {
                return callInt("getWifiStatus");
            }

            std::pair<int, int> getWindowSize()
            {
                return callIntPair("getWindowSize", {0, 0});
            }

            int launchGame(
                const std::string& packageName,
                const std::string& activityName,
                const std::string& action,
                const std::string& category,
                const std::string& mimeType,
                const std::string& data,
                const std::string& startPath,
                const std::string& romPath,
                const std::map<std::string, std::string>& extrasString,
                const std::map<std::string, std::string>& extrasStringArray,
                const std::map<std::string, std::string>& extrasInteger,
                const std::map<std::string, std::string>& extrasBool,
                const std::vector<std::string>& activityFlags,
                bool launchOnOtherScreen)
            {
                ActivityContext context;
                jmethodID id {getMethod(
                    context, "launchGame",
                    "([Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;"
                    "[Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;Z)I")};
                if (id == nullptr)
                    return -1;

                const std::vector<std::string> baseArguments {
                    packageName, activityName, action, category, mimeType, data, startPath, romPath};

                jobjectArray baseArray {toStringArray(context.env, baseArguments)};
                jobjectArray stringArray {toStringArray(context.env, extrasString)};
                jobjectArray stringListArray {toStringArray(context.env, extrasStringArray)};
                jobjectArray integerArray {toStringArray(context.env, extrasInteger)};
                jobjectArray boolArray {toStringArray(context.env, extrasBool)};
                jobjectArray flagArray {toStringArray(context.env, activityFlags)};

                const jint result {context.env->CallIntMethod(
                    context.activity, id, baseArray, stringArray, stringListArray, integerArray,
                    boolArray, flagArray, launchOnOtherScreen ? JNI_TRUE : JNI_FALSE)};

                context.env->DeleteLocalRef(baseArray);
                context.env->DeleteLocalRef(stringArray);
                context.env->DeleteLocalRef(stringListArray);
                context.env->DeleteLocalRef(integerArray);
                context.env->DeleteLocalRef(boolArray);
                context.env->DeleteLocalRef(flagArray);
                clearJavaException(context.env, "launchGame");

                return static_cast<int>(result);
            }

            void onResume()
            {
                callVoid("onNativeFrontendResume");
            }

            void printDeviceInfo()
            {
                ActivityContext context;
                jmethodID id {getMethod(context, "getDeviceInfo", "()Ljava/lang/String;")};
                if (id == nullptr)
                    return;

                jstring value {
                    static_cast<jstring>(context.env->CallObjectMethod(context.activity, id))};
                clearJavaException(context.env, "getDeviceInfo");
                const std::string info {fromJString(context.env, value)};
                if (value != nullptr)
                    context.env->DeleteLocalRef(value);

                if (!info.empty())
                    LOG(LogDebug) << "Android device: " << info;
            }

            void setDataDirectories()
            {
                AndroidVariables::sInternalDataDirectory = callString("getInternalDataDirectory");
                AndroidVariables::sExternalDataDirectory = callString("getAppDataDirectory");

                if (AndroidVariables::sExternalDataDirectory.empty())
                    AndroidVariables::sExternalDataDirectory =
                        AndroidVariables::sInternalDataDirectory;

                FileSystemVariables::sAppDataDirectory =
                    AndroidVariables::sExternalDataDirectory;
            }

            void setROMDirectory()
            {
                AndroidVariables::sROMDirectory = callString("getROMDirectory");
            }

            void setupFontFiles()
            {
                callVoid("setupFontFiles");
            }

            void setupLocalizationFiles()
            {
                callVoid("setupLocalizationFiles");
            }

            bool setupResources(const std::string& buildIdentifier)
            {
                // The frontend's existing caller interprets true as a copy failure.
                return callBool("setupResources", buildIdentifier, true);
            }

            void startConfigurator()
            {
                AndroidVariables::sHold = true;
                callVoid("startConfigurator");
            }
        } // namespace Android
    } // namespace Platform
} // namespace Utils

extern "C" JNIEXPORT void JNICALL
Java_org_esde_plus_MainActivity_nativeSetHold(JNIEnv*, jclass, jboolean hold)
{
    AndroidVariables::sHold = hold == JNI_TRUE;
}

extern "C" JNIEXPORT void JNICALL
Java_org_esde_plus_MainActivity_nativeSetHomeApp(JNIEnv*, jclass, jboolean isHomeApp)
{
    AndroidVariables::sIsHomeApp = isHomeApp == JNI_TRUE;
}

extern "C" JNIEXPORT void JNICALL
Java_org_esde_plus_MainActivity_nativeSetResetTouchOverlay(JNIEnv*, jclass, jboolean reset)
{
    AndroidVariables::sResetTouchOverlay = reset == JNI_TRUE;
}

#endif // __ANDROID__
