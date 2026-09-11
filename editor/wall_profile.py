"""V24 wall contract and lossless palace carrier settings (no EXE addresses)."""
# SPDX-License-Identifier: GPL-2.0-or-later
from dataclasses import dataclass, field
from composite_signal import COMPOSITE_PROFILE_NEW, render_composite_artifacts

CONTRACT = 'pop13-composite-vga-walls-p0-v1'
OVERLAY_CONTRACT = 'pop13-composite-artwork-walls-p0-v1'
CONTRACTS = (CONTRACT, OVERLAY_CONTRACT)
FAMILIES = ('CDUNGEON.DAT', 'CPALACE.DAT')
SLOTS = (0x61, 0x62, 0x63, 0x64, 0x66, 0x67, 0x68, 0x69)
DEFAULTS = (8, 13, 5, 15, 2, 7, 5, 15)
DUNGEON_NAMES = ('Face main', 'Face top', 'Centre bottom', 'Centre main',
    'Right bottom', 'Right main', 'Isolated bottom', 'Isolated main',
    'Left bottom', 'Left main', 'Broad divider', 'Narrow divider',
    'Alternate block', 'Upper left mark', 'Lower left mark', 'Upper right mark', 'Lower right mark')
PALACE_NAMES = ('Face main', 'Face top') + tuple(
    f'{group} divider {variant}' for group in ('Upper', 'Middle upper', 'Middle lower', 'Lower', 'Bottom strip')
    for variant in range(1, 4))

def has_wall_bank(archive):
    if archive.path.name.upper() not in FAMILIES: return False
    header = archive.analysis_by_id(1600)
    count = header.resource.data[0] if header and header.palette else 0
    return bool(count in ((17,19) if archive.path.name.upper()==FAMILIES[1] else (17,)) and
        all((a := archive.analysis_by_id(i)) and a.image and a.image.bits == 4 for i in range(1601,1601+count)))

def wall_contract(archive):
    if not has_wall_bank(archive):return 'original-dos-pop-1.3'
    return OVERLAY_CONTRACT if archive.analysis_by_id(1600).resource.data[0]==19 else CONTRACT

def wall_components(name, contract=CONTRACT):
    """Explicit drawing roles; opaque replacement blocks are not transparent decals."""
    ids=range(1601,1620 if name.upper()==FAMILIES[1] and contract==OVERLAY_CONTRACT else 1618)
    result=[]
    for rid in ids:
        if name.upper()==FAMILIES[1]:role='Transparent overlay' if 1603<=rid<=1617 else 'Base artwork'
        else:role='Opaque replacement' if rid==1613 else 'Transparent overlay' if rid in (1611,1612,1614,1615,1616,1617) else 'Base artwork'
        result.append((rid,resource_name(name,rid).split(' [')[0],role))
    return result

def is_wall_overlay(name,rid):
    if name.upper()==FAMILIES[1]:return 1603<=rid<=1617
    return name.upper()==FAMILIES[0] and 1611<=rid<=1617

def resource_name(name, resource_id):
    if name.upper() not in FAMILIES: return ''
    if 1601 <= resource_id <= 1617:
        names = PALACE_NAMES if name.upper() == FAMILIES[1] else DUNGEON_NAMES
        return names[resource_id-1601] + ' [active wall]'
    if name.upper()==FAMILIES[1] and resource_id in (1618,1619):
        return ('Painted base bottom' if resource_id==1618 else 'Painted base full')+' [active wall]'
    if 361 <= resource_id <= 364: return 'Legacy wall [inactive in V24]'
    if resource_id == 1600: return 'Active wall translation / image table'
    return ''

def carrier_rgb(code):
    bits = bytes((code >> (3-i%4)) & 1 for i in range(64))
    raster = render_composite_artifacts(bits,64,1,COMPOSITE_PROFILE_NEW)
    return tuple(round(sum(raster.pixels[x*3+c] for x in range(12,52))/40) for c in range(3))

@dataclass
class WallSettings:
    patterns: dict[int,int] = field(default_factory=lambda: dict(zip(SLOTS, DEFAULTS)))
    engine_contract: str = CONTRACT

    @classmethod
    def overlays(cls):return cls({},OVERLAY_CONTRACT)

    def validate(self):
        if self.engine_contract==OVERLAY_CONTRACT:
            if self.patterns:raise ValueError('Artwork walls do not accept solid fill settings.')
            return
        if self.engine_contract!=CONTRACT:raise ValueError('Unsupported wall settings contract.')
        if set(self.patterns) != set(SLOTS) or any(type(v) is not int or not 0 <= v <= 15 for v in self.patterns.values()):
            raise ValueError('Palace fills require exactly eight solid New-CGA carriers (0–15).')

    def to_dict(self):
        self.validate()
        if self.engine_contract==OVERLAY_CONTRACT:
            return {'kind':'prince-composite-wall-settings','schema':1,'engine_contract':OVERLAY_CONTRACT,
                'profile':COMPOSITE_PROFILE_NEW,'dither':False,'wall_surface':'dat-artwork','fills':{}}
        return {'kind':'prince-composite-wall-settings','schema':1,'engine_contract':CONTRACT,
            'profile':COMPOSITE_PROFILE_NEW,'dither':False,
            'fills':{f'{slot:02X}':{'carrier':self.patterns[slot], 'preview_rgb':carrier_rgb(self.patterns[slot])} for slot in SLOTS}}

    @classmethod
    def from_dict(cls,value):
        if value.get('engine_contract')==OVERLAY_CONTRACT:
            result=cls.overlays()
            if value!=result.to_dict():raise ValueError('Artwork walls require DAT surfaces and no solid fills.')
            return result
        if (value.get('kind'),value.get('schema'),value.get('engine_contract'),value.get('profile'),value.get('dither')) != (
            'prince-composite-wall-settings',1,CONTRACT,COMPOSITE_PROFILE_NEW,False):
            raise ValueError('Unsupported wall settings contract.')
        fills=value['fills']
        if set(fills) != {f'{slot:02X}' for slot in SLOTS}: raise ValueError('Missing or unknown palace fill slots.')
        result=cls({slot:fills[f'{slot:02X}']['carrier'] for slot in SLOTS})
        result.validate()
        return result

    def table_bytes(self):
        self.validate()
        if self.engine_contract==OVERLAY_CONTRACT:raise ValueError('Artwork walls have no editable EXE fill table.')
        table=bytearray(64)
        for slot,code in self.patterns.items():
            table[(slot&15)*4:(slot&15)*4+4]=bytes([code*17])*4
        return bytes(table)

    @classmethod
    def from_table(cls,raw):
        if len(raw)!=64: raise ValueError('Expected a 64-byte palace table.')
        result=cls({slot:raw[(slot&15)*4]&15 for slot in SLOTS})
        if result.table_bytes()!=raw: raise ValueError('Table contains unsupported or dithered patterns.')
        return result
