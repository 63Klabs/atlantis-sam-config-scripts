"""Unit tests for validate_all_parameters() in cli/config.py.

Tests that the method iterates over all parameter_overrides in a skeleton,
calls validate_parameter() for each, and collects ALL failures rather than
stopping at the first.

Requirements: 7.1, 7.2, 7.3
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'cli'))

from config import ConfigManager


def _create_config_manager():
    """Create a ConfigManager instance with mocked __init__ to avoid AWS calls."""
    with patch.object(ConfigManager, "__init__", lambda self, *args, **kwargs: None):
        cm = ConfigManager.__new__(ConfigManager)
        return cm


class TestValidateAllParametersBasic:
    """Test basic behavior of validate_all_parameters."""

    def test_all_valid_returns_empty_list(self):
        """When all parameters are valid, returns an empty list."""
        cm = _create_config_manager()
        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": {
                                "Prefix": "acme",
                                "ProjectId": "myapp",
                            }
                        }
                    }
                }
            }
        }
        parameters = {
            "Prefix": {
                "Type": "String",
                "AllowedPattern": "^[a-z][a-z0-9]{1,7}$",
                "MinLength": 2,
                "MaxLength": 8,
            },
            "ProjectId": {
                "Type": "String",
                "MinLength": 1,
                "MaxLength": 32,
            },
        }
        failures = cm.validate_all_parameters(skeleton, parameters)
        assert failures == []

    def test_single_failure_returns_one_entry(self):
        """When one parameter is invalid, returns a list with one failure."""
        cm = _create_config_manager()
        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": {
                                "Prefix": "INVALID_UPPER",
                                "ProjectId": "myapp",
                            }
                        }
                    }
                }
            }
        }
        parameters = {
            "Prefix": {
                "Type": "String",
                "AllowedPattern": "^[a-z][a-z0-9]{1,7}$",
                "MinLength": 2,
                "MaxLength": 8,
            },
            "ProjectId": {
                "Type": "String",
                "MinLength": 1,
                "MaxLength": 32,
            },
        }
        failures = cm.validate_all_parameters(skeleton, parameters)
        assert len(failures) == 1
        assert failures[0]["parameter"] == "Prefix"
        assert failures[0]["value"] == "INVALID_UPPER"
        assert "reason" in failures[0]

    def test_multiple_failures_collects_all(self):
        """When multiple parameters are invalid, collects ALL failures."""
        cm = _create_config_manager()
        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": {
                                "Prefix": "INVALID",
                                "StageId": "invalid_stage",
                                "ProjectId": "",
                            }
                        }
                    }
                }
            }
        }
        parameters = {
            "Prefix": {
                "Type": "String",
                "AllowedPattern": "^[a-z][a-z0-9]{1,7}$",
                "MinLength": 2,
                "MaxLength": 8,
            },
            "StageId": {
                "Type": "String",
                "AllowedValues": ["dev", "test", "beta", "stage", "prod"],
            },
            "ProjectId": {
                "Type": "String",
                "MinLength": 1,
                "MaxLength": 32,
            },
        }
        failures = cm.validate_all_parameters(skeleton, parameters)
        assert len(failures) == 3
        failed_params = [f["parameter"] for f in failures]
        assert "Prefix" in failed_params
        assert "StageId" in failed_params
        assert "ProjectId" in failed_params


class TestValidateAllParametersEdgeCases:
    """Test edge cases for validate_all_parameters."""

    def test_empty_parameter_overrides_returns_empty(self):
        """When parameter_overrides is empty, returns empty list."""
        cm = _create_config_manager()
        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": {}
                        }
                    }
                }
            }
        }
        parameters = {
            "Prefix": {"Type": "String", "MinLength": 2},
        }
        failures = cm.validate_all_parameters(skeleton, parameters)
        assert failures == []

    def test_missing_deployments_key_returns_empty(self):
        """When skeleton has no 'deployments' key, returns empty list."""
        cm = _create_config_manager()
        skeleton = {}
        parameters = {"Prefix": {"Type": "String"}}
        failures = cm.validate_all_parameters(skeleton, parameters)
        assert failures == []

    def test_parameter_not_in_template_is_skipped(self):
        """Parameters in skeleton but not in template definitions are skipped."""
        cm = _create_config_manager()
        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": {
                                "UnknownParam": "some_value",
                                "Prefix": "acme",
                            }
                        }
                    }
                }
            }
        }
        parameters = {
            "Prefix": {
                "Type": "String",
                "AllowedPattern": "^[a-z][a-z0-9]{1,7}$",
            },
        }
        failures = cm.validate_all_parameters(skeleton, parameters)
        assert failures == []

    def test_empty_value_with_default_is_valid(self):
        """Empty value for a parameter with a Default defined is valid."""
        cm = _create_config_manager()
        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": {
                                "DeployEnv": "",
                            }
                        }
                    }
                }
            }
        }
        parameters = {
            "DeployEnv": {
                "Type": "String",
                "Default": "DEV",
                "AllowedValues": ["DEV", "TEST", "PROD"],
            },
        }
        failures = cm.validate_all_parameters(skeleton, parameters)
        assert failures == []

    def test_numeric_validation_failure(self):
        """Numeric parameter that violates MinValue/MaxValue is reported."""
        cm = _create_config_manager()
        skeleton = {
            "deployments": {
                "prod": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": {
                                "Timeout": "500",
                            }
                        }
                    }
                }
            }
        }
        parameters = {
            "Timeout": {
                "Type": "Number",
                "MinValue": 1,
                "MaxValue": 300,
            },
        }
        failures = cm.validate_all_parameters(skeleton, parameters)
        assert len(failures) == 1
        assert failures[0]["parameter"] == "Timeout"
        assert failures[0]["value"] == "500"

    def test_failure_dict_has_required_keys(self):
        """Each failure dict has 'parameter', 'value', and 'reason' keys."""
        cm = _create_config_manager()
        skeleton = {
            "deployments": {
                "dev": {
                    "deploy": {
                        "parameters": {
                            "parameter_overrides": {
                                "Prefix": "X",
                            }
                        }
                    }
                }
            }
        }
        parameters = {
            "Prefix": {
                "Type": "String",
                "MinLength": 2,
                "MaxLength": 8,
            },
        }
        failures = cm.validate_all_parameters(skeleton, parameters)
        assert len(failures) == 1
        failure = failures[0]
        assert "parameter" in failure
        assert "value" in failure
        assert "reason" in failure
        assert failure["parameter"] == "Prefix"
        assert failure["value"] == "X"
        assert isinstance(failure["reason"], str)
        assert len(failure["reason"]) > 0
