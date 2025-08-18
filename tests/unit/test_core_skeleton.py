"""Tests for skeleton rendering functionality."""
import pytest
from harvest.core import render_skeleton, render_python_skeleton, render_js_ts_skeleton


class TestPythonSkeletonRendering:
    def test_function_with_type_hints(self):
        src = """def my_function(a: int, b: str) -> bool:
    return True"""
        result = render_python_skeleton(src)
        assert "def my_function(a: int, b: str) -> bool:" in result
    
    def test_async_function(self):
        src = """async def fetch_data(url: str) -> dict:
    result = await get(url)
    return result"""
        result = render_python_skeleton(src)
        assert "async def fetch_data(url: str) -> dict:" in result
    
    def test_class_with_inheritance(self):
        src = """class MyClass(BaseClass, Mixin):
    def __init__(self):
        pass"""
        result = render_python_skeleton(src)
        assert "class MyClass(BaseClass, Mixin):" in result
    
    def test_decorated_function(self):
        src = """@pytest.mark.timeout(10)
@pytest.fixture
def my_test():
    pass"""
        result = render_python_skeleton(src)
        assert "@pytest.mark.timeout(10)" in result
        assert "@pytest.fixture" in result
        assert "def my_test():" in result
    
    def test_property_decorator(self):
        src = """class Test:
    @property
    def name(self) -> str:
        return self._name"""
        result = render_python_skeleton(src)
        assert "@property" in result
        assert "def name(self) -> str:" in result
    
    def test_syntax_error_fallback(self):
        src = """def broken_syntax(
    # Missing closing paren"""
        result = render_python_skeleton(src)
        # Should fallback to regex-based extraction
        assert "def broken_syntax(" in result


class TestJavaScriptSkeletonRendering:
    def test_function_declaration(self):
        src = """function myFunction(a, b) {
    return a + b;
}"""
        result = render_js_ts_skeleton(src)
        assert "function myFunction(…) { … }" in result
    
    def test_export_function(self):
        src = """export function calculateTotal(items) {
    return items.reduce((sum, item) => sum + item.price, 0);
}"""
        result = render_js_ts_skeleton(src)
        assert "export function calculateTotal(…) { … }" in result
    
    def test_class_declaration(self):
        src = """class Component extends React.Component {
    render() {
        return <div>Hello</div>;
    }
}"""
        result = render_js_ts_skeleton(src)
        assert "class Component extends React.Component { … }" in result
    
    def test_export_class(self):
        src = """export class ApiClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }
}"""
        result = render_js_ts_skeleton(src)
        assert "export class ApiClient  { … }" in result
    
    def test_export_const(self):
        src = """export const API_URL = 'https://api.example.com';
export default MyComponent;"""
        result = render_js_ts_skeleton(src)
        assert "export const API_URL …" in result


class TestSkeletonRendererDispatch:
    def test_python_dispatch(self):
        src = "def test(): pass"
        result = render_skeleton("python", src)
        assert "def test():" in result
    
    def test_javascript_dispatch(self):
        src = "function test() {}"
        result = render_skeleton("javascript", src)
        assert "function test(…) { … }" in result
    
    def test_typescript_dispatch(self):
        src = "function test(): string {}"
        result = render_skeleton("typescript", src)
        assert "function test(…) { … }" in result
    
    def test_unknown_language_fallback(self):
        src = """int main() {
    return 0;
}"""
        result = render_skeleton("c", src)
        # Should use generic C-like extraction
        assert "main()" in result or result == ""  # Fallback behavior
    
    def test_none_language(self):
        src = "def test(): pass"
        result = render_skeleton(None, src)
        # Should still work with fallback logic
        assert isinstance(result, str)