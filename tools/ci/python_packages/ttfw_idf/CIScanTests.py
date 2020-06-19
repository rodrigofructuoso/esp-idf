import argparse
import errno
import json
import os
import re
from collections import defaultdict

from find_apps import find_apps
from find_build_apps import BUILD_SYSTEMS, BUILD_SYSTEM_CMAKE
from ttfw_idf.CIAssignExampleTest import CIExampleAssignTest, TestAppsGroup, ExampleGroup

VALID_TARGETS = [
    'esp32',
    'esp32s2',
]

SPECIAL_REFS = [
    'master',
    re.compile(r'^release/v'),
    re.compile(r'^v\d+\.\d+'),
]


def _judge_build_all(args_build_all):
    if args_build_all:
        return True
    if os.getenv('BUILD_ALL_APPS'):
        return True

    ref = os.getenv('CI_COMMIT_REF_NAME')
    pipeline_src = os.getenv('CI_PIPELINE_SOURCE')
    if not ref or not pipeline_src:
        return False

    # scheduled pipeline will build all
    if pipeline_src == 'schedule':
        return True

    # master, release/v..., v1.2.3..., and will build all
    for special_ref in SPECIAL_REFS:
        if isinstance(special_ref, re._pattern_type):
            if special_ref.match(ref):
                return True
        else:
            if ref == special_ref:
                return True
    return False


def main():
    parser = argparse.ArgumentParser(description='Scan the required build tests')
    actions = parser.add_subparsers(dest='action')

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('paths', type=str, nargs='+',
                        help="One or more app paths")
    common.add_argument('-b', '--build-system', choices=BUILD_SYSTEMS.keys(), default=BUILD_SYSTEM_CMAKE)
    common.add_argument('-c', '--ci-config-file', type=str, required=True,
                        help="gitlab ci config target-test file")
    common.add_argument('-o', '--output-path', type=str, required=True,
                        help="output path of the scan result")
    common.add_argument('--preserve', action="store_true",
                        help='add this flag to preserve artifacts for all apps')
    common.add_argument('--build-all', action="store_true",
                        help='add this flag to build all apps')

    actions.add_parser('example_test', parents=[common])
    actions.add_parser('test_apps', parents=[common])

    args = parser.parse_args()

    test_cases = []
    for path in args.paths:
        if args.action == 'example_test':
            assign = CIExampleAssignTest(path, args.ci_config_file, ExampleGroup)
        elif args.action == 'test_apps':
            CIExampleAssignTest.CI_TEST_JOB_PATTERN = re.compile(r'^test_app_test_.+')
            assign = CIExampleAssignTest(path, args.ci_config_file, TestAppsGroup)
        else:
            raise SystemExit(1)  # which is impossible

        test_cases.extend(assign.search_cases())

    if not os.path.exists(args.output_path):
        try:
            os.makedirs(args.output_path)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise e

    '''
    {
        <target>: {
            'test_case_apps': [<app_dir>],   # which is used in target tests
            'standalone_apps': [<app_dir>],  # which is not
        },
        ...
    }
    '''
    scan_info_dict = defaultdict(dict)
    # store the test cases dir, exclude these folders when scan for standalone apps
    exclude_apps = []

    build_system = args.build_system.lower()
    build_system_class = BUILD_SYSTEMS[build_system]

    for target in VALID_TARGETS:
        target_dict = scan_info_dict[target]
        test_case_apps = target_dict['test_case_apps'] = set()
        for case in test_cases:
            app_dir = case.case_info['app_dir']
            app_target = case.case_info['target']
            if app_target.lower() != target.lower():
                continue
            test_case_apps.update(find_apps(build_system_class, app_dir, True, [], target.lower()))
            exclude_apps.append(app_dir)

    for target in VALID_TARGETS:
        target_dict = scan_info_dict[target]
        standalone_apps = target_dict['standalone_apps'] = set()
        for path in args.paths:
            standalone_apps.update(find_apps(build_system_class, path, True, exclude_apps, target.lower()))

    build_all = _judge_build_all(args.build_all)
    test_case_apps_preserve_default = True if build_system == 'cmake' else False

    for target in VALID_TARGETS:
        apps = []
        for app_dir in scan_info_dict[target]['test_case_apps']:
            apps.append({
                'app_dir': app_dir,
                'build': True,
                'preserve': args.preserve or test_case_apps_preserve_default
            })
        for app_dir in scan_info_dict[target]['standalone_apps']:
            apps.append({
                'app_dir': app_dir,
                'build': build_all if build_system == 'cmake' else True,
                'preserve': (args.preserve and build_all) if build_system == 'cmake' else False
            })
        output_path = os.path.join(args.output_path, 'scan_{}_{}.json'.format(target.lower(), build_system))
        if apps:
            with open(output_path, 'w') as fw:
                fw.writelines([json.dumps(app) + '\n' for app in apps])


if __name__ == '__main__':
    main()
