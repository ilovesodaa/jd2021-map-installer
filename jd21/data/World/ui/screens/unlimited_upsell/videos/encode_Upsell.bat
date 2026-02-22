rem -- here set the path to your ffmpeg exe (usually you have it in Teabox (JD_CODE\main\tools\apps\TeaBox\Script\Utilities\FFmpeg or JD_DATA\main\engine\Tools\TeaBox\Script\Utilities\FFmpeg)
set ffmpeg=D:\JD_DATA\main\engine\Tools\TeaBox\Script\Utilities\FFmpeg\ffmpeg.exe 

rem -- here put the path to the files for the PNGs (for now \\ubisoft.org\projects\JD2019\MRC\GRAPH\_UbiLogoVideoJD19\180711_UBI_JD_2019_4K) and the wav (in D:\JD_DATA\main\data\World\videos)
set include=-i "\\ubisoft.org\projects\JD2019\MRC\GRAPH\_TrailerJDU\PNG\JDU_UPSELL_VIDEO_FINAL.%%05d.png" -r 25 -i "D:\JD_DATA\main\data\World\ui\screens\unlimited_upsell\videos\JDU_UPSELL_TRAILER_mix.wav" 

rem -- VP9 720 : switch -- 
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1280x720 -c:v libvpx-vp9 -b:v 4M -threads 8 -tile-columns 6 -frame-parallel 1 -auto-alt-ref 1 -lag-in-frames 25 -pass 1 -speed 2 -an -passlogfile TrailerJDU_vp9_720 -f null -
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1280x720 -c:v libvpx-vp9 -b:v 4M -threads 8 -tile-columns 6 -frame-parallel 1 -auto-alt-ref 1 -lag-in-frames 25 -pass 2 -speed 1 -c:a libvorbis -b:a 112k -passlogfile TrailerJDU_vp9_720 -y TrailerJDU.vp9.720.webm

rem -- VP8 1080 : ps4, xb1 -- 
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1920x1080 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 4 -qmin 0 -qmax 51 -profile:v 0 -pass 1 -speed 1 -an -passlogfile TrailerJDU_vp8_1080 -f null -
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1920x1080 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 4 -qmin 0 -qmax 51 -profile:v 0 -pass 2 -speed 0 -c:a libvorbis -b:a 112k -passlogfile TrailerJDU_vp8_1080 -y TrailerJDU.hd.webm

rem -- VP8 1216x720 : wiiU, PC -- 
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1216x720 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 2 -qmin 0 -qmax 51 -profile:v 2 -pass 1 -speed 1 -an -passlogfile TrailerJDU_vp8_720p2 -f null -
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1216x720 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 2 -qmin 0 -qmax 51 -profile:v 2 -pass 2 -speed 0 -c:a libvorbis -b:a 112k -passlogfile TrailerJDU_vp8_720p2 -y TrailerJDU.webm

pause