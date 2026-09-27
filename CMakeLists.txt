cmake_minimum_required(VERSION 3.25)

project(hfdns
    VERSION 0.1.0
    DESCRIPTION "Hyperfast DNS Load Balancer"
    LANGUAGES CXX)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(FATAL_ERROR "hfdns targets Linux (epoll, SO_REUSEPORT, recvmmsg). Build inside WSL2 or Docker.")
endif()

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "Build type" FORCE)
endif()

option(HFDNS_WERROR "Treat warnings as errors in project targets" ON)
option(HFDNS_BUILD_TESTS "Build tests" ON)

set(HFDNS_WARNINGS -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wsign-conversion
    -Wnon-virtual-dtor -Wold-style-cast -Wnull-dereference -Wimplicit-fallthrough)
if(HFDNS_WERROR)
    list(APPEND HFDNS_WARNINGS -Werror)
endif()

find_package(PkgConfig REQUIRED)
find_package(yaml-cpp REQUIRED)
find_package(spdlog REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(Threads REQUIRED)

find_path(HTTPLIB_INCLUDE_DIR httplib.h REQUIRED)
find_library(HTTPLIB_LIBRARY cpp-httplib REQUIRED)
add_library(hfdns_httplib INTERFACE)
target_include_directories(hfdns_httplib SYSTEM INTERFACE ${HTTPLIB_INCLUDE_DIR})
target_link_libraries(hfdns_httplib INTERFACE ${HTTPLIB_LIBRARY})

if(HFDNS_BUILD_TESTS)
    enable_testing()
    find_package(GTest REQUIRED)
endif()

add_subdirectory(core)
