//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  shader-state.cpp
//
//  Written for ES-DE-Plus. Executes production program creation/uniform setters
//  against counted GL state, including shader switches and program rebuilding.
//

#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <glm/glm.hpp>
#include <iostream>
#include <map>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

using GLuint = unsigned int;
using GLenum = unsigned int;
using GLint = int;
using GLfloat = float;
using GLchar = char;
constexpr int GL_TRUE {1}, GL_FALSE {0}, GL_INVALID_VALUE {0x501}, GL_INVALID_OPERATION {0x502};
constexpr int GL_COMPILE_STATUS {1}, GL_LINK_STATUS {2};
#define GL_CHECK_ERROR(function) (function)
#define LOG(level) std::cerr
unsigned int activeProgram {0}, nextProgram {1}, writes {0};
using Values = std::map<std::string, std::vector<double>>;
std::map<GLuint, Values> programs;
std::map<std::pair<GLuint, GLint>, std::string> locations;
GLuint glCreateProgram()
{
    auto id = nextProgram++;
    programs[id] = {};
    return id;
}
GLuint glCreateShader(GLenum) { return 1; }
void glShaderSource(GLuint, int, const char**, void*) {}
void glCompileShader(GLuint) {}
void glGetShaderiv(GLuint, GLenum, GLint* status) { *status = GL_TRUE; }
void glAttachShader(GLuint, GLuint) {}
void glLinkProgram(GLuint id) { programs[id].clear(); }
void glGetProgramiv(GLuint, GLenum, GLint* status) { *status = GL_TRUE; }
void glEnableVertexAttribArray(GLint) {}
GLint glGetAttribLocation(GLuint, const char*) { return -1; }
GLint glGetUniformLocation(GLuint id, const char* name)
{
    const auto location = static_cast<GLint>(locations.size() + 1);
    locations[{id, location}] = name;
    return location;
}
void glUseProgram(GLuint id) { activeProgram = id; }
void glDeleteProgram(GLuint id) { programs.erase(id); }
void write(GLint location, std::vector<double> value)
{
    programs.at(activeProgram)[locations.at({activeProgram, location})] = value;
    ++writes;
}
void glUniform1i(GLint location, int value) { write(location, {static_cast<double>(value)}); }
void glUniform1ui(GLint location, GLuint value) { write(location, {static_cast<double>(value)}); }
void glUniform1f(GLint location, GLfloat value) { write(location, {value}); }
void glUniform2f(GLint location, GLfloat x, GLfloat y) { write(location, {x, y}); }
void glUniform4f(GLint location, GLfloat x, GLfloat y, GLfloat z, GLfloat w)
{
    write(location, {x, y, z, w});
}
void glUniformMatrix4fv(GLint location, int count, bool transpose, const GLfloat* values)
{
    if (count != 1 || transpose)
        std::abort();
    write(location, std::vector<double>(values, values + 16));
}
#include "shader-class.inc"
#include "shader-methods.inc"
void ShaderOpenGL::printProgramInfoLog(GLuint) {}
void ShaderOpenGL::printShaderInfoLog(GLuint, GLenum, bool) {}

void draw(ShaderOpenGL& shader)
{
    shader.activateShaders();
    shader.setModelViewProjectionMatrix(glm::mat4 {1});
    shader.setTextureSamplers();
    shader.setTextureSize({100, 200});
    shader.setClipRegion({0, 0, 0, 0});
    shader.setBrightness(1);
    shader.setOpacity(1);
    shader.setSaturation(1);
    shader.setDimming(1);
    shader.setCornerRadius(0);
    shader.setReflectionsFalloff(0);
    shader.setBlurStrength(0);
    shader.setFlags(2);
}
int main()
{
    int checks {0};
    auto require = [&](bool condition, const char* message) {
        if (!condition) {
            std::fprintf(stderr, "FAIL: shader state %s\n", message);
            std::exit(1);
        }
        ++checks;
    };
    ShaderOpenGL first;
    require(first.createProgram(), "production program creation succeeds");
    draw(first);
    require(writes == 13 && programs.at(first.getProgramID()).size() == 13,
            "first draw publishes every uniform including zero/default values and both samplers");
    const auto baseline = programs.at(first.getProgramID());
    draw(first);
    require(writes == 13 && programs.at(first.getProgramID()) == baseline,
            "identical draw preserves all GL values without resending any uniforms");
    for (const auto& item : std::vector<std::pair<void (ShaderOpenGL::*)(GLfloat), std::string>> {
             {&ShaderOpenGL::setBrightness, "brightness"},
             {&ShaderOpenGL::setOpacity, "opacity"},
             {&ShaderOpenGL::setSaturation, "saturation"},
             {&ShaderOpenGL::setDimming, "dimming"},
             {&ShaderOpenGL::setCornerRadius, "cornerRadius"},
             {&ShaderOpenGL::setReflectionsFalloff, "reflectionsFalloff"},
             {&ShaderOpenGL::setBlurStrength, "blurStrength"}}) {
        const auto before = writes;
        (first.*item.first)(0.25f);
        (first.*item.first)(0.25f);
        require(writes == before + 1 &&
                    programs.at(first.getProgramID()).at(item.second) == std::vector<double> {0.25},
                "a changed scalar reaches GL exactly once");
        (first.*item.first)(0.75f);
        require(writes == before + 2 &&
                    programs.at(first.getProgramID()).at(item.second) == std::vector<double> {0.75},
                "a later changed scalar is never suppressed");
    }
    auto before = writes;
    first.setTextureSize({300, 400});
    first.setTextureSize({300, 400});
    require(writes == before + 1 &&
                programs.at(first.getProgramID()).at("texSize") == std::vector<double>({300, 400}),
            "texture extent changes");
    before = writes;
    first.setClipRegion({1, 2, 3, 4});
    first.setClipRegion({1, 2, 3, 4});
    require(writes == before + 1 && programs.at(first.getProgramID()).at("clipRegion") ==
                                        std::vector<double>({1, 2, 3, 4}),
            "clip-region changes");
    before = writes;
    first.setModelViewProjectionMatrix(glm::mat4 {2});
    first.setModelViewProjectionMatrix(glm::mat4 {2});
    require(writes == before + 1 && programs.at(first.getProgramID()).at("MVPMatrix")[0] == 2,
            "transform changes");
    before = writes;
    first.setFlags(8);
    first.setFlags(8);
    require(writes == before + 1 &&
                programs.at(first.getProgramID()).at("shaderFlags") == std::vector<double> {8},
            "material-flag changes");
    const auto changed = programs.at(first.getProgramID());
    ShaderOpenGL second;
    require(second.createProgram(), "second independent program creation");
    before = writes;
    draw(second);
    require(writes == before + 13 && programs.at(second.getProgramID()) == baseline,
            "a second program uploads its own uniforms despite identical values");
    first.activateShaders();
    before = writes;
    first.setFlags(8);
    first.setTextureSamplers();
    first.setOpacity(0.75f);
    require(writes == before && programs.at(first.getProgramID()) == changed,
            "switching programs preserves each program's values and cache");
    second.activateShaders();
    const auto previous = first.getProgramID();
    first.deleteProgram(previous);
    require(first.createProgram() && first.getProgramID() != previous,
            "production program rebuilding creates a new program");
    before = writes;
    draw(first);
    require(writes == before + 13 && programs.at(first.getProgramID()) == baseline,
            "rebuilding invalidates every cache field, including sampler and zero values");
    before = writes;
    const auto location = first.mShaderFlags;
    first.mShaderFlags = -1;
    first.setFlags(42);
    require(writes == before, "inactive uniform is not submitted");
    first.mShaderFlags = location;
    first.setFlags(42);
    require(writes == before + 1 && programs.at(first.getProgramID()).at("shaderFlags")[0] == 42,
            "inactive uniform never poisons the last successfully submitted value");
    std::printf("PASS: %d production shader-state/cache checks\n", checks);
}
