//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  shader-loader.cpp
//
//  Written for ES-DE-Plus. Execute production shader loading with missing/failed
//  optional programs and retain hard failure for inherited required programs.
//
#include <cstdlib>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>
#define LOG(level) messages
constexpr int GL_VERTEX_SHADER {1}, GL_FRAGMENT_SHADER {2};
std::ostringstream messages;
struct ResourceManager {
    inline static bool present {true};
    static ResourceManager& getInstance()
    {
        static ResourceManager value;
        return value;
    }
    bool fileExists(const std::string&) { return present; }
};
struct ShaderOpenGL {
    inline static std::string fail;
    inline static unsigned int loaded {0};
    std::string path;
    void loadShaderFile(const std::string& value, int)
    {
        path = value;
        ++loaded;
    }
    bool createProgram() { return path != fail; }
};
struct RendererOpenGL {
    std::vector<std::shared_ptr<ShaderOpenGL>> mShaderProgramVector;
    bool loadShaders();
};
#include "shader-loader.inc"
int main()
{
    unsigned int checks {0};
    auto require = [&](bool value) {
        if (!value)
            std::abort();
        ++checks;
    };
    RendererOpenGL normal;
    require(normal.loadShaders());
    require(normal.mShaderProgramVector.size() == 5 && ShaderOpenGL::loaded == 10);
    require(normal.mShaderProgramVector[4]->path == ":/shaders/glsl/search.glsl");
    require(normal.mShaderProgramVector[4] != normal.mShaderProgramVector[0]);
    ResourceManager::present = false;
    RendererOpenGL missing;
    const auto before = ShaderOpenGL::loaded;
    require(missing.loadShaders());
    require(ShaderOpenGL::loaded - before == 8 && missing.mShaderProgramVector.size() == 5);
    require(missing.mShaderProgramVector[4] == missing.mShaderProgramVector[0]);
    ResourceManager::present = true;
    ShaderOpenGL::fail = ":/shaders/glsl/search.glsl";
    RendererOpenGL rejected;
    require(rejected.loadShaders());
    require(rejected.mShaderProgramVector.size() == 5);
    require(rejected.mShaderProgramVector[4] == rejected.mShaderProgramVector[0]);
    ShaderOpenGL::fail = ":/shaders/glsl/core.glsl";
    RendererOpenGL broken;
    require(!broken.loadShaders() && broken.mShaderProgramVector.empty());
    ShaderOpenGL::fail = ":/shaders/glsl/blur_horizontal.glsl";
    RendererOpenGL brokenBlur;
    require(!brokenBlur.loadShaders() && brokenBlur.mShaderProgramVector.size() == 1);
    std::cout << "PASS: " << checks << " production shader loading/fallback checks\n";
}
