from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class ModExtraFile:
    key: str
    version: str
    url: str

@dataclass
class ModChapterData:
    description: Optional[str] = None
    data_file_url: Optional[str] = None
    data_file_version: Optional[str] = None
    extra_files: List[ModExtraFile] = field(default_factory=list)

    def is_valid(self) -> bool:
        return bool(self.data_file_url or self.extra_files)

@dataclass
class ModInfo:
    key: str
    name: str
    version: str
    author: str
    tagline: str
    game_version: str
    description_url: str
    downloads: int
    modtype: str
    is_verified: bool
    icon_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    hide_mod: bool = False
    is_xdelta: bool = False
    ban_status: bool = False
    files: Dict[str, ModChapterData] = field(default_factory=dict)
    demo_url: Optional[str] = None
    demo_version: Optional[str] = None
    created_date: Optional[str] = None
    last_updated: Optional[str] = None
    screenshots_url: List[str] = field(default_factory=list)

    def get_chapter_data(self, chapter_id: int) -> Optional[ModChapterData]:
        chapter_map = {0: '0', 1: '1', 2: '2', 3: '3', 4: '4', -1: 'demo'}
        if self.modtype == 'undertale' and chapter_id == 0:
            return self.files.get('undertale')
        file_key = chapter_map.get(chapter_id)
        return self.files.get(file_key) if file_key else None

    def is_valid_for_demo(self) -> bool:
        if self.modtype != 'deltarunedemo':
            return False
        if self.key.startswith('local_'):
            return bool(self.files and self.files.get('demo'))
        return bool(self.demo_url and self.demo_version)