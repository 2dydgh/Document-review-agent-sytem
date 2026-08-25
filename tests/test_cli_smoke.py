from app.cli import main


def test_main_no_args_returns_zero_and_prints_help(capsys):
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "docsuree" in captured.out.lower()
