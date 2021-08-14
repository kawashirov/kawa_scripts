@echo off
pushd %~dp0
git subtree push --prefix gh-pages origin gh-pages
popd
