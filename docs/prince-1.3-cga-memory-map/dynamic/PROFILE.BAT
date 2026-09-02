@echo off
echo DOSBOX_STOCK_CONTROL_PROFILE> PROFILE.TXT
echo machine:>> PROFILE.TXT
config -get dosbox machine>> PROFILE.TXT
echo.>> PROFILE.TXT
echo memsize:>> PROFILE.TXT
config -get dosbox memsize>> PROFILE.TXT
echo.>> PROFILE.TXT
echo xms:>> PROFILE.TXT
config -get dos xms>> PROFILE.TXT
echo.>> PROFILE.TXT
echo ems:>> PROFILE.TXT
config -get dos ems>> PROFILE.TXT
echo.>> PROFILE.TXT
echo umb:>> PROFILE.TXT
config -get dos umb>> PROFILE.TXT
echo.>> PROFILE.TXT
echo mpu401:>> PROFILE.TXT
config -get midi mpu401>> PROFILE.TXT
echo.>> PROFILE.TXT
echo mididevice:>> PROFILE.TXT
config -get midi mididevice>> PROFILE.TXT
echo.>> PROFILE.TXT
echo sbtype:>> PROFILE.TXT
config -get sblaster sbtype>> PROFILE.TXT
echo.>> PROFILE.TXT
echo sbbase:>> PROFILE.TXT
config -get sblaster sbbase>> PROFILE.TXT
echo.>> PROFILE.TXT
echo irq:>> PROFILE.TXT
config -get sblaster irq>> PROFILE.TXT
echo.>> PROFILE.TXT
echo dma:>> PROFILE.TXT
config -get sblaster dma>> PROFILE.TXT
echo.>> PROFILE.TXT
echo hdma:>> PROFILE.TXT
config -get sblaster hdma>> PROFILE.TXT
echo.>> PROFILE.TXT
echo pcspeaker:>> PROFILE.TXT
config -get speaker pcspeaker>> PROFILE.TXT
echo.>> PROFILE.TXT
