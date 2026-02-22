
set ffmpeg=C:\ffmpeg.exe
set include=-i "UpsellKids/JDU_UPSELL_TRAILER_KIDS_%%04d.png" -r 25 -i "TrailerJDUKids.wav"


rem rem -- VP9 1080 : switch -- 
rem START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1920x1080 -c:v libvpx-vp9 -b:v 8M -threads 8 -tile-columns 6 -frame-parallel 1 -auto-alt-ref 1 -lag-in-frames 25 -pass 1 -speed 2 -an -passlogfile UbiLogoJD_PAL_vp9_1080 -f null -
rem START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1920x1080 -c:v libvpx-vp9 -b:v 8M -threads 8 -tile-columns 6 -frame-parallel 1 -auto-alt-ref 1 -lag-in-frames 25 -pass 2 -speed 1 -c:a libvorbis -b:a 112k -passlogfile UbiLogoJD_PAL_vp9_1080 -y UbiLogoJD_PAL.vp9.1080.webm

rem rem -- VP9 720 : switch -- 
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1280x720 -c:v libvpx-vp9 -b:v 8M -threads 8 -tile-columns 6 -frame-parallel 1 -auto-alt-ref 1 -lag-in-frames 25 -pass 1 -speed 2 -an -passlogfile TrailerJDUKids_vp9_720 -f null -
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1280x720 -c:v libvpx-vp9 -b:v 8M -threads 8 -tile-columns 6 -frame-parallel 1 -auto-alt-ref 1 -lag-in-frames 25 -pass 2 -speed 1 -c:a libvorbis -b:a 112k -passlogfile TrailerJDUKids_vp9_720 -y TrailerJDUKids.vp9.720.webm

rem -- VP8 1080 : ps4, xb1 -- 
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1920x1080 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 4 -qmin 0 -qmax 51 -profile:v 0 -pass 1 -speed 1 -an -passlogfile TrailerJDUKids_vp8_1080 -f null -
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1920x1080 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 4 -qmin 0 -qmax 51 -profile:v 0 -pass 2 -speed 0 -c:a libvorbis -b:a 112k -passlogfile TrailerJDUKids_vp8_1080 -y TrailerJDUKids.hd.webm

rem -- VP8 1216x720 : wiiU, PC -- 
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1216x720 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 2 -qmin 0 -qmax 51 -profile:v 2 -pass 1 -speed 1 -an -passlogfile TrailerJDUKids_vp8_720p2 -f null -
START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1216x720 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 2 -qmin 0 -qmax 51 -profile:v 2 -pass 2 -speed 0 -c:a libvorbis -b:a 112k -passlogfile TrailerJDUKids_vp8_720p2 -y TrailerJDUKids.webm

rem rem -- VP8 1280x720 : x360 -- 
rem START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1280x720 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 4 -qmin 0 -qmax 51 -profile:v 0 -pass 1 -speed 1 -an -passlogfile UbiLogoJD_PAL_vp8_720 -f null -
rem START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1280x720 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 4 -qmin 0 -qmax 51 -profile:v 0 -pass 2 -speed 0 -c:a libvorbis -b:a 112k -passlogfile UbiLogoJD_PAL_vp8_720 -y UbiLogoJD_PAL.x360.webm

rem rem -- VP8 1280x720 : ps3 -- 
rem START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1280x720 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 8 -qmin 0 -qmax 51 -profile:v 0 -pass 1 -speed 1 -an -passlogfile UbiLogoJD_PAL_vp8_720_ps3 -f null -
rem START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 1280x720 -c:v libvpx -b:v 8000k -quality good -threads 8 -slices 8 -qmin 0 -qmax 51 -profile:v 0 -pass 2 -speed 0 -c:a libvorbis -b:a 112k -passlogfile UbiLogoJD_PAL_vp8_720_ps3 -y UbiLogoJD_PAL.ps3.webm

rem rem -- VP8 512x384 : wii -- 
rem START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 512x384 -c:v libvpx -b:v 2300k -threads 8 -slices 0 -qmin 0 -qmax 51 -profile:v 2 -pass 1 -speed 1 -an -passlogfile UbiLogoJD_PAL_vp8_384_wii -f null -
rem START /B /WAIT /MIN /I /low %ffmpeg% %include% -r 25 -g 25 -keyint_min 25 -reserve_index_space 16384 -pix_fmt yuv420p -s 512x384 -c:v libvpx -b:v 2300k -threads 8 -slices 0 -qmin 0 -qmax 51 -profile:v 2 -pass 2 -speed 0 -c:a libvorbis -b:a 112k -passlogfile UbiLogoJD_PAL_vp8_384_wii -y UbiLogoJD_PAL.wii.webm




