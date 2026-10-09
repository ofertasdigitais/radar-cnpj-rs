import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app


class ResolveLocalAdminCredentialTests(unittest.TestCase):
    """Cobre app.resolve_local_admin_credential() sem depender do DPAPI real
    do Windows: o subprocesso PowerShell é sempre simulado (mockado)."""

    def test_explicit_env_vars_take_priority_and_never_touch_powershell(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict("os.environ", {"RADAR_ADMIN_USER": "admin", "RADAR_ADMIN_PASSWORD": "segredo"}, clear=True), \
             patch.object(app, "DATA_DIR", Path(directory)), \
             patch.object(app.subprocess, "run") as run:
            app.resolve_local_admin_credential()
            run.assert_not_called()
            self.assertEqual(app.os.environ["RADAR_ADMIN_USER"], "admin")
            self.assertEqual(app.os.environ["RADAR_ADMIN_PASSWORD"], "segredo")

    def test_non_windows_never_touches_powershell(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".radar-credential.xml").write_text("qualquer coisa", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True), \
                 patch.object(app, "DATA_DIR", Path(directory)), \
                 patch.object(app.os, "name", "posix"), \
                 patch.object(app.subprocess, "run") as run:
                app.resolve_local_admin_credential()
                run.assert_not_called()
                self.assertNotIn("RADAR_ADMIN_USER", app.os.environ)

    def test_missing_credential_file_is_a_silent_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {}, clear=True), \
                 patch.object(app, "DATA_DIR", Path(directory)), \
                 patch.object(app.os, "name", "nt"), \
                 patch.object(app.subprocess, "run") as run:
                app.resolve_local_admin_credential()
                run.assert_not_called()
                self.assertNotIn("RADAR_ADMIN_USER", app.os.environ)

    def test_windows_with_credential_file_populates_env_from_powershell_output(self):
        with tempfile.TemporaryDirectory() as directory:
            credential_file = Path(directory) / ".radar-credential.xml"
            credential_file.write_text("<Objs>fake clixml</Objs>", encoding="utf-8")
            fake_result = MagicMock(returncode=0, stdout="admin-local\ns3nh4-secreta\n", stderr="")
            with patch.dict("os.environ", {}, clear=True), \
                 patch.object(app, "DATA_DIR", Path(directory)), \
                 patch.object(app.os, "name", "nt"), \
                 patch.object(app.subprocess, "run", return_value=fake_result) as run:
                app.resolve_local_admin_credential()
                self.assertEqual(app.os.environ["RADAR_ADMIN_USER"], "admin-local")
                self.assertEqual(app.os.environ["RADAR_ADMIN_PASSWORD"], "s3nh4-secreta")
                # A credencial nunca deve ser lida diretamente pelo Python: só o
                # PowerShell (via DPAPI) toca o arquivo; o Python só recebe o
                # caminho por variável de ambiente do subprocesso, nunca a senha
                # por argumento de linha de comando.
                args, kwargs = run.call_args
                command = args[0]
                self.assertNotIn("s3nh4-secreta", " ".join(command))
                self.assertEqual(kwargs["env"]["RADAR_CRED_PATH"], str(credential_file))
                self.assertIn("-", command)  # script entra via stdin, não por -Command embutido

    def test_powershell_failure_leaves_server_without_admin_bypass(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".radar-credential.xml").write_text("corrompido", encoding="utf-8")
            fake_result = MagicMock(returncode=2, stdout="", stderr="")
            with patch.dict("os.environ", {}, clear=True), \
                 patch.object(app, "DATA_DIR", Path(directory)), \
                 patch.object(app.os, "name", "nt"), \
                 patch.object(app.subprocess, "run", return_value=fake_result):
                app.resolve_local_admin_credential()
                self.assertNotIn("RADAR_ADMIN_USER", app.os.environ)
                self.assertNotIn("RADAR_ADMIN_PASSWORD", app.os.environ)

    def test_powershell_unavailable_does_not_crash_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".radar-credential.xml").write_text("qualquer coisa", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True), \
                 patch.object(app, "DATA_DIR", Path(directory)), \
                 patch.object(app.os, "name", "nt"), \
                 patch.object(app.subprocess, "run", side_effect=FileNotFoundError("powershell.exe not found")):
                app.resolve_local_admin_credential()  # não deve levantar exceção
                self.assertNotIn("RADAR_ADMIN_USER", app.os.environ)

    def test_malformed_powershell_output_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".radar-credential.xml").write_text("qualquer coisa", encoding="utf-8")
            fake_result = MagicMock(returncode=0, stdout="somente-um-usuario\n", stderr="")
            with patch.dict("os.environ", {}, clear=True), \
                 patch.object(app, "DATA_DIR", Path(directory)), \
                 patch.object(app.os, "name", "nt"), \
                 patch.object(app.subprocess, "run", return_value=fake_result):
                app.resolve_local_admin_credential()
                self.assertNotIn("RADAR_ADMIN_USER", app.os.environ)

    def test_session_secret_file_is_reused_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / ".radar-credential.xml").write_text("qualquer coisa", encoding="utf-8")
            (data_dir / ".radar-session-secret").write_text("segredo-persistido-123\n", encoding="utf-8")
            fake_result = MagicMock(returncode=0, stdout="admin-local\nsenha\n", stderr="")
            with patch.dict("os.environ", {}, clear=True), \
                 patch.object(app, "DATA_DIR", data_dir), \
                 patch.object(app.os, "name", "nt"), \
                 patch.object(app.subprocess, "run", return_value=fake_result):
                app.resolve_local_admin_credential()
                self.assertEqual(app.os.environ["RADAR_SESSION_SECRET"], "segredo-persistido-123")

    def test_existing_session_secret_env_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / ".radar-credential.xml").write_text("qualquer coisa", encoding="utf-8")
            (data_dir / ".radar-session-secret").write_text("segredo-do-arquivo", encoding="utf-8")
            fake_result = MagicMock(returncode=0, stdout="admin-local\nsenha\n", stderr="")
            with patch.dict("os.environ", {"RADAR_SESSION_SECRET": "ja-definido"}, clear=True), \
                 patch.object(app, "DATA_DIR", data_dir), \
                 patch.object(app.os, "name", "nt"), \
                 patch.object(app.subprocess, "run", return_value=fake_result):
                app.resolve_local_admin_credential()
                self.assertEqual(app.os.environ["RADAR_SESSION_SECRET"], "ja-definido")


if __name__ == "__main__":
    unittest.main()
