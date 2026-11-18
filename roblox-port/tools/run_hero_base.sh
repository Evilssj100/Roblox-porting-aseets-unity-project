#!/bin/bash
# exact extraction + exact Blender base + texel maps for one hero bundle
set -e
B=$1; K=$2
R=/home/claude/roblox-porting-aseets-unity-project
W=/home/claude/spso-port/work/heroes/$K
T=/home/claude/spso-port/tools
mkdir -p $W
cd $W
python3 $T/unity_hero_anim_exact.py $R/$B.unity3d $W/anim > $W/log_anim.txt 2>&1
python3 $T/unity_hero_to_blend_exact.py $R/$B.unity3d $W/anim $W/${K}_exact.blend > $W/log_blend.txt 2>&1
python3 $T/uv_bake_maps.py $W/${K}_exact.blend $W/maps > $W/log_maps.txt 2>&1
echo done > $W/BASE_DONE
