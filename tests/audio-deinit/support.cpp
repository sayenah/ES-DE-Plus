//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  support.cpp
//
//  Written for ES-DE-Plus. In-memory settings and logging for the audio-only executable.
//  AudioManager, Sound, their callback and SDL are the real implementations.
//

#include "Log.h"
#include "Settings.h"

Settings::Settings() = default;

Settings* Settings::getInstance()
{
    static Settings settings;
    return &settings;
}

int Settings::getInt(const std::string& /*name*/) { return 100; }

bool Settings::setInt(const std::string& /*name*/, int /*value*/) { return false; }

bool Settings::getBool(const std::string& /*name*/) { return true; }

Log::~Log() = default;

LogLevel Log::getReportingLevel() { return LogError; }

std::ostringstream& Log::get(LogLevel /*level*/) { return mOutStringStream; }
