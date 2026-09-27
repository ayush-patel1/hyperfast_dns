#include "hfdns/cli.hpp"

#include <format>

namespace hfdns {

std::string_view cli_usage() noexcept {
    return "usage: hfdns-lb --config <path> [--check-config] [--log-level <level>]\n"
           "       hfdns-lb --version | --help\n"
           "\n"
           "  -c, --config <path>     YAML configuration file (required)\n"
           "      --check-config      validate the configuration and exit\n"
           "      --log-level <lvl>   error|warn|info|debug|trace (LOG_LEVEL env overrides)\n"
           "  -V, --version           print version and exit\n"
           "  -h, --help              print this help and exit\n"
           "\n"
           "exit codes: 0 ok, 1 runtime error, 2 usage error, 3 invalid configuration\n";
}

Result<CliOptions> parse_cli(std::span<const std::string_view> args) {
    CliOptions opts;
    for (std::size_t i = 0; i < args.size(); ++i) {
        const auto arg = args[i];
        auto value = [&](std::string_view flag) -> Result<std::string> {
            if (i + 1 >= args.size() || args[i + 1].starts_with("-")) {
                return make_error(ErrorCode::InvalidArgument,
                                  std::format("option {} requires a value", flag));
            }
            return std::string(args[++i]);
        };

        if (arg == "-c" || arg == "--config") {
            auto v = value(arg);
            if (!v) {
                return std::unexpected(v.error());
            }
            opts.config_path = std::move(*v);
        } else if (arg.starts_with("--config=")) {
            opts.config_path = std::string(arg.substr(9));
        } else if (arg == "--check-config") {
            opts.check_config = true;
        } else if (arg == "--log-level") {
            auto v = value(arg);
            if (!v) {
                return std::unexpected(v.error());
            }
            opts.log_level = std::move(*v);
        } else if (arg == "-V" || arg == "--version") {
            opts.show_version = true;
        } else if (arg == "-h" || arg == "--help") {
            opts.show_help = true;
        } else {
            return make_error(ErrorCode::InvalidArgument,
                              std::format("unknown argument '{}'", arg));
        }
    }
    if (!opts.show_help && !opts.show_version && opts.config_path.empty()) {
        return make_error(ErrorCode::InvalidArgument, "--config is required");
    }
    return opts;
}

}  // namespace hfdns
