# Implementation Plan: Network Role ARN Support

## Overview

Extend `role_arn` support to the `network` infrastructure type by adding `'network'` to seven existing infra-type gate checks in `cli/config.py`, introducing the `NetworkServiceRoleArn` defaults key, and updating property-based tests to reflect the new behavior. All changes follow the existing patterns established for `pipeline` and `storage`.

## Tasks

- [x] 1. Update existing test strategies to include network in role_arn set
  - [x] 1.1 Update test strategies in `tests/test_config_role_arn.py`
    - Change `preservation_infra_type` from `st.sampled_from(['network', 'service-role'])` to `st.just('service-role')`
    - Change `bug_condition_infra_type` from `st.sampled_from(['pipeline', 'storage'])` to `st.sampled_from(['pipeline', 'storage', 'network'])`
    - These tests will FAIL until the code changes in task 2 are applied
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 2. Implement code changes in `cli/config.py`
  - [x] 2.1 Add NetworkServiceRoleArn default resolution in `__init__` (~line 127-131)
    - Add `elif self.infra_type == 'network' and 'NetworkServiceRoleArn' in self.defaults['atlantis']:` branch after the pipeline branch
    - Set `self.defaults['atlantis']['role_arn'] = self.defaults['atlantis']['NetworkServiceRoleArn']`
    - _Requirements: 4.1, 4.2, 3.2_

  - [x] 2.2 Add network to `gather_atlantis_deploy_parameters()` infra-type check (~line 465)
    - Change `if infra_type in ['pipeline', 'storage']:` to `if infra_type in ['pipeline', 'storage', 'network']:`
    - This enables interactive role_arn prompting for network deployments
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 2.3 Add network to `set_future_defaults()` role_arn key mapping (~line 1028-1034)
    - Add `elif self.infra_type == 'network': default_param = 'NetworkServiceRoleArn'` after the pipeline branch
    - This ensures role_arn is saved under the correct key for network deployments
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 2.4 Add NetworkServiceRoleArn resolution in skeleton default resolution (~line 1197-1203)
    - Add `elif self.infra_type == 'network' and atlantis_defaults.get('NetworkServiceRoleArn'):` branch
    - Set the role_arn default from `atlantis_defaults['NetworkServiceRoleArn']`
    - _Requirements: 3.2_

  - [x] 2.5 Add network to `generate_skeleton()` infra-type check (~line 1227)
    - Change `if self.infra_type in ['pipeline', 'storage']:` to `if self.infra_type in ['pipeline', 'storage', 'network']:`
    - This includes role_arn in the skeleton output for network
    - _Requirements: 3.1_

  - [x] 2.6 Add network to `build_config()` infra-type check (~line 1943)
    - Change `if infra_type in ['pipeline', 'storage']:` to `if infra_type in ['pipeline', 'storage', 'network']:`
    - This includes role_arn in atlantis default deploy parameters during interactive config build
    - _Requirements: 2.1, 2.3_

  - [x] 2.7 Add network to `build_config_headless()` infra-type check (~line 2060)
    - Change `if infra_type in ['pipeline', 'storage']:` to `if infra_type in ['pipeline', 'storage', 'network']:`
    - This includes role_arn in atlantis default deploy parameters during headless config build
    - _Requirements: 2.2, 2.3_

- [x] 3. Checkpoint - Verify existing tests pass with code changes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Add new property-based tests for Properties 3, 4, and 5
  - [x] 4.1 Write property test for NetworkServiceRoleArn default resolution (Property 3)
    - **Property 3: NetworkServiceRoleArn Default Resolution**
    - Test that when `NetworkServiceRoleArn` is in defaults and `infra_type='network'`, `__init__` resolves `defaults['atlantis']['role_arn']` to the NetworkServiceRoleArn value
    - Mock `ConfigManager.__init__` partially to test the default resolution logic
    - **Validates: Requirements 4.1, 3.2**

  - [x] 4.2 Write property test for infra-type key isolation (Property 4)
    - **Property 4: Infra-Type Key Isolation**
    - Generate three distinct role ARN values for Storage, Pipeline, and Network
    - Initialize ConfigManager for each infra_type with all three keys present in defaults
    - Assert each type resolves ONLY its own key, no cross-contamination
    - **Validates: Requirements 4.3**

  - [x] 4.3 Write property test for future defaults persistence (Property 5)
    - **Property 5: Future Defaults Persistence Under Correct Key**
    - Test that `set_future_defaults()` for network saves under `NetworkServiceRoleArn` key
    - Mock `click.confirm` to return True, verify the key name in the resulting defaults dict
    - **Validates: Requirements 5.2**

- [x] 5. Final checkpoint - Ensure full test suite passes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The code changes in task 2 are all mechanical additions of `'network'` to existing infra-type lists
- Property tests use `hypothesis` which is already configured in the project
- Run tests with: `source .ve/bin/activate && python -m pytest tests/test_config_role_arn.py -v`
- All changes are contained in two files: `cli/config.py` and `tests/test_config_role_arn.py`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7"] },
    { "id": 2, "tasks": ["4.1", "4.2", "4.3"] }
  ]
}
```
