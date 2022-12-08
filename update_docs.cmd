@echo off
setlocal 
pushd %~dp0
set PYTHONPATH=%PYTHONPATH%;%CD%\blender_autocomplete\3.0;%CD%\pdoc
python.exe -m pdoc -f -o .tmp_doc --html kawa_scripts
del /f /q gh-pages\*.html
xcopy /s /v /f /h /r .tmp_doc\kawa_scripts\* gh-pages
popd
endlocal
