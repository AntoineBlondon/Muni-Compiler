__version__ = "0.1.0"

def compile_muni(source: str) -> str:
    from .cli import compile_to_wat
    return compile_to_wat(source)

__all__ = ["__version__", "compile_muni"]
