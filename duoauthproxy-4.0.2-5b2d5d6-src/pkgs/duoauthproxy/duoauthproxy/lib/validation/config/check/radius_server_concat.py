from duoauthproxy.lib.validation.config.check import base
from duoauthproxy.lib.validation.connectivity.connectivity_results import ConfigCheckResult
from duoauthproxy.lib.validation.config.config_toolbox import STANDARD_CONFIG_TOOLBOX


def check_radius_server_concat(config, toolbox=STANDARD_CONFIG_TOOLBOX):
    """
    Validates the [radius_server_concat] section of the auth proxy config.

    Args:
        config (ConfigDict): The radius server auto config to check
        toolbox (ConfigTestToolbox): Toolbox used to execute the tests

    Returns:
        ConfigCheckResult containing any configuration errors
    """
    problems = check_required_keys(config, toolbox)
    problems += check_config_values(config, toolbox)
    problems += check_config_dependencies(config, toolbox)

    return ConfigCheckResult(problems)


def check_required_keys(config, toolbox):
    """
    Validates that all required keys for an [radius_server_concat] section
    are present in the config.

    Args:
        config (ConfigDict): The config object to check the required config for
        toolbox (ConfigTestToolbox): Toolbox used to execute the tests

    Returns:
        list of ConfigResult
    """
    return base.check_common_required_radius_keys(config, toolbox)


def check_config_values(config, toolbox):
    """
    Validates the values for provided config in the [radius_server_concat]
    section

    Args:
        config (ConfigDict): The config object to check the optional config for
        toolbox (ConfigTestToolbox): Toolbox used to execute the tests

    Returns:
        list of ConfigResult
    """
    problems = []
    config_test_resolver = base.get_basic_radius_server_resolver(config, toolbox)

    # Add radius server concat specific keys
    config_test_resolver.update({
        'delimiter': toolbox.test_is_string,
        'delimited_password_length': toolbox.test_is_positive_int,
    })

    problems += base.run_config_value_checks(config, config_test_resolver)
    problems += base.check_for_unexpected_keys(config, toolbox, config_test_resolver)
    problems += base.check_basic_radius_server_protected_usage(config, toolbox)
    return problems


def check_config_dependencies(config, toolbox):
    problems = base.check_radius_secret_radius_ip_balance(config)
    problems += base.check_basic_server_config_dependencies(config, toolbox)
    return problems
