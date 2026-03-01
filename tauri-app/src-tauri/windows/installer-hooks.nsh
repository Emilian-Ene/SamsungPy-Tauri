!macro NSIS_HOOK_POSTUNINSTALL
  RMDir /r "$LOCALAPPDATA\\SamsungMdcTauri"
  RMDir /r "$APPDATA\\SamsungMdcTauri"
  RMDir /r "$LOCALAPPDATA\\Samsung MCD"
  RMDir /r "$APPDATA\\Samsung MCD"
  RMDir /r "$LOCALAPPDATA\\com.ionut.samsungmdctauri"
  RMDir /r "$APPDATA\\com.ionut.samsungmdctauri"
!macroend
