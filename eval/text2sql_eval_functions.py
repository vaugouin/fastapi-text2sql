import importlib.util
import pathlib
from types import ModuleType


def _load_impl() -> ModuleType:
    impl_path = pathlib.Path(__file__).with_name("text2sql-eval-functions.py")
    spec = importlib.util.spec_from_file_location("text2sql_eval_functions_impl", impl_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module from {impl_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_impl = _load_impl()

format_api_version = _impl.format_api_version
safe_json_loads = _impl.safe_json_loads
format_single_line_record = _impl.format_single_line_record

evaluate_dataframe_assertions = _impl.evaluate_dataframe_assertions
format_detailed_results_for_db = _impl.format_detailed_results_for_db
