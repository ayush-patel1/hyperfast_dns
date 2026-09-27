#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <format>
#include <string_view>
#include <vector>

#include "hfdns/admin_server.hpp"
#include "hfdns/cli.hpp"
#include "hfdns/config.hpp"
#include "hfdns/duration.hpp"
#include "hfdns/log.hpp"
#include "hfdns/version.hpp"

namespace {

using namespace hfdns;

// Returns false if the text could not be written (e.g. stdout closed).
bool emit(std::FILE* stream, std::string_view text) {
    return std::fwrite(text.data(), 1, text.size(), stream) == text.size() &&
           std::fputc('\n', stream) != EOF && std::fflush(stream) == 0;
}

// stdout output *is* the result of --help/--version/--check-config, so failing to write it is
// a runtime error. Diagnostics on stderr have nowhere else to go and are best-effort.
int emit_result(std::string_view text) {
    return emit(stdout, text) ? kExitOk : kExitRuntimeError;
}
void emit_diagnostic(std::string_view text) {
    (void)emit(stderr, text);
}

std::optional<std::string_view> env_log_level() {
    const char* v =
        std::getenv("LOG_LEVEL");  // NOLINT(concurrency-mt-unsafe): read before threads start
    return v ? std::optional<std::string_view>(v) : std::nullopt;
}

std::string summary(const Config& cfg) {
    return std::format(
        "config OK: {} listener(s), {} worker(s){}, {} backend(s), {} region(s), policy={}, "
        "upstream.timeout={}",
        cfg.listeners.size(), cfg.workers, cfg.workers_auto ? " (auto)" : "", cfg.backends.size(),
        cfg.regions.size(), to_string(cfg.routing.policy), format_duration(cfg.upstream.timeout));
}

// Blocks SIGINT/SIGTERM in every thread (call before spawning any), so the main
// thread can wait for them synchronously instead of using an async handler.
sigset_t block_shutdown_signals() {
    sigset_t set;
    sigemptyset(&set);
    sigaddset(&set, SIGINT);
    sigaddset(&set, SIGTERM);
    pthread_sigmask(SIG_BLOCK, &set, nullptr);
    return set;
}

int run(const CliOptions& opts) {
    auto cfg = load_config_file(opts.config_path, detect_hardware_threads());
    if (!cfg) {
        emit_diagnostic(cfg.error().to_string());
        return cfg.error().code == ErrorCode::IoError ? kExitRuntimeError : kExitConfigInvalid;
    }
    if (opts.log_level) {
        auto lvl = log::parse_level(*opts.log_level);
        if (!lvl) {
            emit_diagnostic(std::format("--log-level: {}", lvl.error().message));
            return kExitUsage;
        }
        cfg->logging.level = *lvl;
    }
    if (opts.check_config) {
        return emit_result(summary(*cfg));
    }

    const sigset_t signals = block_shutdown_signals();
    auto level = log::init(cfg->logging.level, env_log_level());
    if (!level) {
        emit_diagnostic(level.error().message);
        return kExitUsage;
    }

    log::info("starting", {{"version", kVersion},
                           {"workers", cfg->workers},
                           {"listeners", cfg->listeners.size()},
                           {"backends", cfg->backends.size()},
                           {"policy", to_string(cfg->routing.policy)},
                           {"log_level", log::to_string(*level)}});

    AdminServer admin(
        {.address = cfg->admin.address, .port = cfg->admin.port, .version = kVersion});
    if (auto started = admin.start(); !started) {
        log::error("startup_failed", {{"reason", started.error().message}});
        log::shutdown();
        return kExitRuntimeError;
    }

    int sig = 0;
    sigwait(&signals, &sig);
    log::info("shutdown_requested", {{"signal", sig == SIGINT ? "SIGINT" : "SIGTERM"}});
    admin.stop();
    log::info("stopped");
    log::shutdown();
    return kExitOk;
}

}  // namespace

int main(int argc, char** argv) {
    const std::vector<std::string_view> args(argv + 1, argv + argc);
    auto opts = parse_cli(args);
    if (!opts) {
        emit_diagnostic(std::format("error: {}\n\n{}", opts.error().message, cli_usage()));
        return kExitUsage;
    }
    if (opts->show_help) {
        auto usage = cli_usage();
        usage.remove_suffix(usage.ends_with('\n') ? 1 : 0);
        return emit_result(usage);
    }
    if (opts->show_version) {
        return emit_result(std::format("hfdns-lb {}", kVersion));
    }
    return run(*opts);
}
