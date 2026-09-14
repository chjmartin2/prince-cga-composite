"""Replay native room draw recipes in the 640x200 CGA signal domain."""
# SPDX-License-Identifier: GPL-2.0-or-later
from dataclasses import dataclass
from array import array
from prince_dat import hardware_palette_for_resource, translated_index, COMPOSITE_PROFILE_NEW, RenderedRaster
from composite_project import initial_mode6_bits, source_pixels_for_edit
from composite_signal import render_composite_artifacts
from wall_profile import WallSettings, is_wall_overlay

@dataclass
class PreviewFrame:
    bits: bytearray
    hits: list
    owners: array

    def raster(self):
        return render_composite_artifacts(self.bits,640,200,COMPOSITE_PROFILE_NEW)

    def pick(self,x,y):
        if 0<=x<640 and 0<=y<200:
            owner=self.owners[y*640+x]
            if owner:return self.hits[owner-1][:2]
        return None

def render_recipe(commands, archives, projects=None, settings=None, fill_table=None, mono_table=None):
    projects=projects or {}
    settings=settings or WallSettings()
    output=bytearray(640*200)
    owners=array('H',[0])*(640*200)
    hits=[]; cache={}
    fill_table=fill_table or bytes(64)
    mono_table=mono_table or fill_table
    for cmd in commands:
        if (not settings.palace_overlays and cmd[0]=='i' and cmd[1]=='CPALACE.DAT'
                and is_wall_overlay(cmd[1],cmd[2])):continue
        if cmd[0]=='f':
            _,x,y,w,h,color=cmd
            table=settings.table_bytes() if 0x61<=color<=0x69 else fill_table
            hits.append(('WALLS',color,x*2,y,w*2,h))
            for yy in range(max(0,y),min(200,y+h)):
                for xx in range(max(0,x*2),min(640,(x+w)*2)):
                    pattern=table[(color&15)*4+((yy&1)*2)+(xx//8&1)]
                    output[yy*640+xx]=(pattern>>(7-xx%8))&1
                    owners[yy*640+xx]=len(hits)
            continue
        _,name,rid,x,y,blit=cmd
        key=(name,rid)
        if key not in cache:
            a=archives[name]; analysis=a.analysis_by_id(rid)
            if analysis is None or analysis.image is None:raise ValueError(f'Missing preview image {name}/{rid}')
            image=analysis.image; palette=hardware_palette_for_resource(a,analysis.resource)
            bits=initial_mode6_bits(image,palette)
            pixels=image.pixels
            project=projects.get(name)
            edit=project.edits.get(analysis.resource.index) if project else None
            if edit:
                bits=edit.variant_bits(0 if 0 in edit.enabled_phases else edit.fallback_phase)
                pixels=source_pixels_for_edit(image,edit,palette,phase=edit.fallback_phase)
            cache[key]=(image,bits,pixels)
        image,bits,pixels=cache[key]
        # Recipe positions include the bank-specific native P0 placement rule.
        width=image.width*2
        if image.bits==1:
            bits=bytes(value for bit in bits for value in (bit,bit))
        hits.append((name,rid,x*2,y,width,image.height))
        for sy in range(max(0,-y),min(image.height,200-y)):
            for sx in range(max(0,-x*2),min(width,640-x*2)):
                src=sy*width+sx; dst=(y+sy)*640+x*2+sx
                value=bits[src]; pixel=pixels[sy*image.width+sx//2]
                drawn=False
                if blit==0:output[dst]=value;drawn=True
                elif blit==2:output[dst]|=value;drawn=bool(value)
                elif blit==3:output[dst]^=value;drawn=bool(value)
                elif blit==9:
                    if pixel:output[dst]=0;drawn=True
                elif blit==16:
                    if pixel:output[dst]=value;drawn=True
                elif blit>=0x40:
                    if pixel:
                        pattern=mono_table[(blit&15)*4+((y+sy)&3)]
                        output[dst]=(pattern>>(7-(x*2+sx)%8))&1
                        drawn=True
                else:raise ValueError(f'Unsupported preview blitter {blit}')
                if drawn:owners[dst]=len(hits)
    return PreviewFrame(output,hits,owners)

def wall_test_board(name,room_commands,components=None):
    """Show every wall component at native geometry, with transparent surround."""
    commands=[]
    for i,rid in enumerate(components or range(1601,1618)):
        commands.append(['i',name,rid,4+(i%7)*45,(i//7)*66,16])
    return commands

def without_overlays(commands,family):
    return [c for c in commands if not (c[0]=='i' and c[1]==family and is_wall_overlay(c[1],c[2]))]

def overlay_inspector(commands, name, rid, archives, projects=None, settings=None, fill_table=None, mono_table=None):
    """Show one actual draw operation, its write mask, and its composite result.

    Decode entire signal frames BEFORE cropping. The checkerboard is an editor
    annotation applied afterwards; it never enters the composite signal decoder.
    """
    if (settings and not settings.palace_overlays and name=='CPALACE.DAT'
            and is_wall_overlay(name,rid)):
        raise ValueError('Palace overlays are disabled for this game. Edit its painted base artwork instead.')
    match=next((i for i,c in enumerate(commands) if c[0]=='i' and c[1:3]==[name,rid]),None)
    if match is None:raise ValueError('This image is not drawn in this room. Use Find in room or choose another variation.')
    cmd=commands[match]
    args=(archives,projects,settings,fill_table,mono_table)
    before=render_recipe(commands[:match],*args)
    after=render_recipe(commands[:match+1],*args)
    layer=render_recipe([cmd],*args)
    before_rgb=before.raster();after_rgb=after.raster()
    image=archives[name].analysis_by_id(rid).image
    x,y=cmd[3]*2,cmd[4]
    left=max(0,min(576,x+image.width-32));top=max(0,min(152,y+image.height//2-24))
    pixels=bytearray(bytes((20,26,34))*(640*200))
    for yy in range(48):
        for xx in range(64):
            offset=(top+yy)*640+left+xx
            a=before_rgb.pixels[offset*3:offset*3+3]
            b=after_rgb.pixels[offset*3:offset*3+3]
            # Cyan explicitly means written pixels, including opaque black.
            mask=bytes((50,220,235)) if layer.owners[offset] else bytes((70,70,76) if (xx//4+yy//4)&1 else (108,108,114))
            for panel,rgb in enumerate((a,mask,b)):
                for dy in (0,1,2):
                    dst=((28+yy*3+dy)*640+8+panel*216+xx*3)*3
                    pixels[dst:dst+9]=rgb*3
    return RenderedRaster(640,200,bytes(pixels),3,'composite'),(left,top),cmd
