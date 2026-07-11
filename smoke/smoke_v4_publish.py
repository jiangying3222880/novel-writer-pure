"""
smoke_v4_publish — 发布模块测试

验证发布导出功能。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    print("=" * 60)
    print("smoke_v4_publish — 发布模块测试")
    print("=" * 60)

    # 1. Exporter 类导入
    from app.services.exporter import TxtExporter, DocxExporter, BookExporter
    print("1. Exporter classes: OK")

    # 2. TxtExporter 基础
    txt_exp = TxtExporter()
    assert hasattr(txt_exp, "export")
    print("2. TxtExporter: OK")

    # 3. DocxExporter 基础
    docx_exp = DocxExporter()
    assert hasattr(docx_exp, "export")
    print("3. DocxExporter: OK")

    # 4. BookExporter 类存在
    assert hasattr(BookExporter, "export")
    print("4. BookExporter class: OK")

    # 5. Publish tab 存在性
    publish_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "ui", "tabs", "publish_tab.py"
    )
    assert os.path.exists(publish_path), "publish_tab.py not found"
    print("5. publish_tab.py exists: OK")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
