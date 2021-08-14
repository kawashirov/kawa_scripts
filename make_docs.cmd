@echo off
setlocal 
pushd %~dp0
set PYTHONPATH=%PYTHONPATH%;%CD%\blender_autocomplete\2.83;%CD%\pdoc
python.exe -m pdoc -f -o .tmp_doc --html kawa_scripts
popd
endlocal
