; BiliEmojiDD 安装程序（NSIS + MUI2）
;
; 由 packaging/build.py 调用，参数从命令行传入：
;   makensis /DVERSION=0.1.0 /DSRCDIR=...\dist\BiliEmojiDD /DOUTFILE=...\setup.exe \
;            /DLICENSE=...\LICENSE /DPUBLISHER=gcnanmu installer.nsi
;
; 两个刻意的选择：
;   1. **当前用户级安装**（RequestExecutionLevel user + $LOCALAPPDATA），装卸都不弹 UAC；
;      注册表也就只写 HKCU。
;   2. **卸载默认保留用户数据**（%APPDATA%\biliEmojiDD 下的配置 / 缓存 / 搜索历史），
;      只问一句是否一并删除——重装或升级不该把 Cookie 和设置弄丢。

Unicode true

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APP_NAME "BiliEmojiDD"
!define APP_EXE "BiliEmojiDD.exe"
!define APP_DATA_DIR "$APPDATA\biliEmojiDD"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Name "${APP_NAME} ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${VERSION}.0"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "LegalCopyright" "Copyright (C) 2026 ${PUBLISHER} - GPL-3.0-or-later"
VIAddVersionKey "FileDescription" "${APP_NAME} 安装程序"

!define MUI_ABORTWARNING
!define MUI_ICON "${SRCDIR}\static\logo.ico"
!define MUI_UNICON "${SRCDIR}\static\logo.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 ${APP_NAME}"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Section "安装" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${SRCDIR}\*.*"

  CreateShortCut "$SMPROGRAMS\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ; 「应用和功能」里显示占用大小
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "创建桌面快捷方式" SecDesktop
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
SectionEnd

LangString DESC_SecMain ${LANG_SIMPCHINESE} "${APP_NAME} 主程序（必需）。"
LangString DESC_SecDesktop ${LANG_SIMPCHINESE} "在桌面创建 ${APP_NAME} 的快捷方式。"

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} $(DESC_SecMain)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} $(DESC_SecDesktop)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR"

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APP_NAME}"

  ; 配置 / 缓存 / 搜索历史默认留着：重装或换版本不该丢 Cookie 和设置
  IfFileExists "${APP_DATA_DIR}\*.*" 0 done
    MessageBox MB_YESNO|MB_ICONQUESTION \
      "是否同时删除配置、缓存与搜索历史？$\n$\n${APP_DATA_DIR}$\n$\n选「否」将保留，重装后设置仍在。" \
      IDNO done
    RMDir /r "${APP_DATA_DIR}"
  done:
SectionEnd
