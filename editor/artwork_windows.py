"""Workspace exchange, palace color swatches, and live native room previews."""
# SPDX-License-Identifier: GPL-2.0-or-later
import hashlib
import json
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from artwork_workspace import ArtworkWorkspace, import_package, json_bytes
from wall_profile import FAMILIES, SLOTS, CONTRACT, carrier_rgb, resource_name, wall_components, is_wall_overlay
from wall_preview import render_recipe, wall_test_board, without_overlays, overlay_inspector
from prince_dat import png_bytes

class ArtworkController:
    def __init__(self,app):
        self.app=app;self.workspace=None;self.windows=[]

    def ensure(self):
        if self.workspace:return self.workspace
        folder=self.app.archive.path.parent if self.app.archive else None
        if folder is None:
            folder=filedialog.askdirectory(parent=self.app,title='Open composite artwork/game folder')
        if not folder:return None
        try:self.workspace=ArtworkWorkspace.open_folder(folder)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Artwork workspace',str(exc),parent=self.app);return None
        self.sync()
        if self.app.composite_editor:self.attach_editor(self.app.composite_editor)
        return self.workspace

    def sync(self):
        window=self.app.composite_editor
        if self.workspace and window and window.winfo_exists():
            name=window.archive.path.name.upper()
            if name in self.workspace.projects and window.archive.data==self.workspace.archives[name].data:
                self.workspace.bind(window.archive,window.project)

    def attach_editor(self,window):
        if not self.workspace:return
        name=window.archive.path.name.upper()
        if name in self.workspace.projects and window.archive.data==self.workspace.archives[name].data:
            window.project=self.workspace.projects[name]
            if window.orientation_workspace:window.orientation_workspace.project=window.project
            window.workspace_managed=True
            window.set_analysis(window.source_analysis or self.app.current)

    def open_package(self):
        if self.workspace and not self.confirm_close():return
        filename=filedialog.askopenfilename(parent=self.app,title='Import artwork exchange ZIP',filetypes=[('Artwork ZIP','*.zip')])
        if not filename:return
        parent=filedialog.askdirectory(parent=self.app,title='Choose a parent folder for the imported workspace')
        if not parent:return
        destination=Path(parent)/Path(filename).stem
        count=1
        while destination.exists():
            destination=Path(parent)/(Path(filename).stem+f'-{count}');count+=1
        try:
            imported=import_package(filename,destination)
            self.sync()
            for window in list(self.windows):window.close()
            if self.app.composite_editor:
                self.app.composite_editor.destroy();self.app.composite_editor=None
            self.workspace=imported
            self.app.open_archive(destination/'CDUNGEON.DAT')
            self.app.status_var.set(f'Artwork workspace: {destination}')
        except (OSError,ValueError,KeyError) as exc:messagebox.showerror('Import failed',str(exc),parent=self.app)

    def export(self):
        workspace=self.ensure()
        if not workspace:return False
        filename=filedialog.asksaveasfilename(parent=self.app,title='Export complete artwork project',
            initialfile='Composite-Artwork.zip',defaultextension='.zip',filetypes=[('Artwork ZIP','*.zip')])
        if not filename:return False
        try:
            self.sync();workspace.export_zip(filename)
            for p in workspace.projects.values():p.dirty=False
            self.app.status_var.set(f'Exported complete artwork: {filename}')
            return True
        except (OSError,ValueError,KeyError) as exc:messagebox.showerror('Export failed',str(exc),parent=self.app)
        return False

    def preview(self,family):
        workspace=self.ensure()
        if not workspace:return
        if not workspace.recipes:
            messagebox.showinfo('Room previews','Open the complete experimental game folder or import its artwork ZIP to load the matching room preview recipes.',parent=self.app);return
        window=WallPreviewWindow(self,family);self.windows.append(window)

    def edit_resource(self,name,rid):
        self.sync()
        if self.app.archive is None or self.app.archive.path.name.upper()!=name:
            self.app.open_archive(self.workspace.archives[name].path)
        self.app.current=self.app.archive.analysis_by_id(rid)
        iid=str(self.app.current.resource.index)
        if not self.app.tree.exists(iid):
            self.app.search_var.set('');self.app.filter_var.set('All resources');self.app.refresh_tree()
        self.app.tree.selection_set(iid);self.app.tree.focus(iid);self.app.tree.see(iid)
        self.app.on_tree_selection()
        self.app.open_composite_editor()
        self.attach_editor(self.app.composite_editor)
        self.app.composite_editor.set_analysis(self.app.current)

    def confirm_close(self):
        if not self.workspace:return True
        self.sync()
        if self.workspace.dirty or any(p.dirty for p in self.workspace.projects.values()):
            answer=messagebox.askyesnocancel('Save artwork project','Export the complete artwork project before closing?',parent=self.app)
            if answer is None:return False
            if answer:return self.export()
        return True

class WallPreviewWindow(tk.Toplevel):
    def __init__(self,controller,family):
        super().__init__(controller.app)
        self.controller=controller;self.family=family;self.workspace=controller.workspace
        self.title(('Palace' if family==FAMILIES[1] else 'Dungeon')+' Preview — live composite artwork')
        self.geometry('1280x880');self.minsize(1060,700)
        self.rooms=[r for r in self.workspace.recipes['rooms'] if r['family']==family]
        self.plain_palace=family==FAMILIES[1] and not self.workspace.settings.palace_overlays
        self.roomvar=tk.StringVar(value=self.label(self.rooms[0]));self.viewvar=tk.StringVar(value='Game room' if self.plain_palace else 'Overlay inspector')
        self.components=wall_components(family,self.workspace.settings.engine_contract,self.workspace.settings.palace_overlays)
        self.selected=1619 if self.plain_palace else next(rid for rid,label,role in self.components if role=='Transparent overlay')
        self.signature=None;self.photo=None;self.frame=None;self.origin=(0,0);self.size=(640,480)
        controls=ttk.Frame(self,padding=8);controls.pack(fill='x')
        ttk.Label(controls,text='View:').pack(side='left')
        views=('Game room','Wall test board') if self.plain_palace else ('Overlay inspector','Game room','Base walls only','Wall test board')
        ttk.Combobox(controls,textvariable=self.viewvar,values=views,state='readonly',width=18).pack(side='left',padx=6)
        ttk.Combobox(controls,textvariable=self.roomvar,values=[self.label(r) for r in self.rooms],state='readonly',width=22).pack(side='left',padx=6)
        ttk.Button(controls,text='Export preview PNG…',command=self.export_png).pack(side='right')
        body=ttk.Frame(self);body.pack(fill='both',expand=True)
        list_font=tkfont.nametofont('TkDefaultFont',root=self)
        browser_width=max(300,max(list_font.measure(f'{rid}  {label}') for rid,label,_ in self.components)+80)
        browser=ttk.Frame(body,padding=8,width=browser_width);browser.pack(side='left',fill='y');browser.pack_propagate(False)
        heading='Palace painted wall artwork' if self.plain_palace else 'Wall artwork and overlay variations'
        ttk.Label(browser,text=heading,font=('Segoe UI',10,'bold'),wraplength=browser_width-20).pack(anchor='w',pady=(0,8))
        if self.plain_palace:
            ttk.Label(browser,text='Palace overlays disabled',wraplength=browser_width-20).pack(anchor='w',pady=(0,8))
        # Ttk's default row height does not grow with Windows-scaled fonts.
        # Keep the hit area taller than the actual text, with room to breathe.
        row_height=max(28,list_font.metrics('linespace')+max(8,round(self.winfo_fpixels('4p'))))
        ttk.Style(self).configure('Overlay.Treeview',font=list_font,rowheight=row_height)
        selector=ttk.Frame(browser);selector.pack(fill='both',expand=True)
        self.component_tree=ttk.Treeview(selector,show='tree',selectmode='browse',height=8,style='Overlay.Treeview')
        scrollbar=ttk.Scrollbar(selector,orient='vertical',command=self.component_tree.yview)
        self.component_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y')
        self.component_tree.pack(side='left',fill='both',expand=True)
        for role in ('Transparent overlay','Opaque replacement','Base artwork'):
            entries=[c for c in self.components if c[2]==role]
            if not entries:continue
            self.component_tree.insert('','end',iid=role,text=role+'s',open=True)
            for rid,label,_ in entries:self.component_tree.insert(role,'end',iid=str(rid),text=f'{rid}  {label}')
        self.component_tree.bind('<<TreeviewSelect>>',self.select_component)
        self.component_tree.bind('<Double-1>',lambda e:self.edit_selected())
        self.details=tk.StringVar()
        ttk.Label(browser,textvariable=self.details,wraplength=browser_width-25,justify='left').pack(fill='x',pady=8)
        ttk.Button(browser,text='Edit selected image…',command=self.edit_selected).pack(fill='x',pady=3)
        ttk.Button(browser,text='Find in room',command=self.find_in_room).pack(fill='x',pady=3)
        help_text=('Double-click a painted base to edit it.\nChanges appear live in the palace preview.\n\nDungeon overlays remain available in Dungeon Preview.' if self.plain_palace else
            'Cyan = pixels the overlay draws.\nCheckerboard = transparent holes.\n\nDouble-click a variation to paint it.\nImage and transparency edits appear live.')
        ttk.Label(browser,text=help_text,wraplength=browser_width-25,justify='left').pack(fill='x',pady=8)
        self.canvas=tk.Canvas(body,background='#141a22',highlightthickness=0);self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.bind('<Button-1>',self.pick);self.canvas.bind('<Configure>',lambda e:self.paint())
        self.canvas.bind('<Motion>',self.hover)
        if family==FAMILIES[1] and self.workspace.settings.engine_contract==CONTRACT:self.build_swatches()
        self.status=tk.StringVar(value='Click a wall component to edit it. Static rooms use the native engine draw order.')
        ttk.Label(self,textvariable=self.status,padding=8).pack(fill='x')
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.component_tree.selection_set(str(self.selected));self.find_in_room()
        self.timer=self.after(20,self.refresh)

    @staticmethod
    def label(room):return f"Level {room['level']:02} / Room {room['room']:02}"

    def select_component(self,event=None):
        chosen=self.component_tree.selection()
        if not chosen or not chosen[0].isdigit():return
        self.selected=int(chosen[0]);self.signature=None
        self.viewvar.set('Overlay inspector' if is_wall_overlay(self.family,self.selected) else 'Game room')
        self.find_in_room()

    def edit_selected(self):self.controller.edit_resource(self.family,self.selected)

    def find_in_room(self):
        def contains(room):return any(c[0]=='i' and c[1:3]==[self.family,self.selected] for c in room['commands'])
        current=next(r for r in self.rooms if self.label(r)==self.roomvar.get())
        if contains(current):return
        found=next((r for r in self.rooms if contains(r)),None)
        if found:self.roomvar.set(self.label(found))
        elif hasattr(self,'status'):self.status.set('No native room uses this image. It remains available on the wall test board.')

    def build_swatches(self):
        panel=ttk.LabelFrame(self,text='Palace brick fills — eight solid New-CGA colors',padding=8);panel.pack(fill='x',padx=8,pady=6)
        self.slotvar=tk.IntVar(value=SLOTS[0]);self.slotbuttons={}
        slots=ttk.Frame(panel);slots.pack(fill='x')
        for i,slot in enumerate(SLOTS):
            button=tk.Radiobutton(slots,text=f"{'Gold' if i<4 else 'Blue'} {i%4+1}",value=slot,variable=self.slotvar,indicatoron=False,width=10)
            button.pack(side='left',padx=2);self.slotbuttons[slot]=button
        choices=ttk.Frame(panel);choices.pack(fill='x',pady=(8,0))
        ttk.Label(choices,text='Choose color:').pack(side='left',padx=(0,6))
        for code in range(16):
            rgb=carrier_rgb(code);color='#%02x%02x%02x'%rgb
            tk.Button(choices,text=f'{code:X}',background=color,foreground='black' if sum(rgb)>360 else 'white',width=3,
                command=lambda c=code:self.choose(c)).pack(side='left',padx=1)

    def choose(self,code):
        self.workspace.settings.patterns[self.slotvar.get()]=code
        self.workspace.dirty=True

    def refresh(self):
        try:
            self.controller.sync()
            state={'room':self.roomvar.get(),'view':self.viewvar.get(),'selected':self.selected,'fills':self.workspace.settings.patterns,
                'projects':{n:{i:bytes(e.variant_bits(e.fallback_phase)).hex()+bytes(e.source_zero_mask).hex() for i,e in p.edits.items()}
                    for n,p in self.workspace.projects.items() if n in (self.family,'PRINCE.DAT')}}
            signature=hashlib.sha256(json_bytes(state)).digest()
            if signature!=self.signature:
                room=next(r for r in self.rooms if self.label(r)==self.roomvar.get())
                view=self.viewvar.get()
                commands=wall_test_board(self.family,room['commands'],[c[0] for c in self.components]) if view=='Wall test board' else room['commands']
                if view=='Base walls only':commands=without_overlays(commands,self.family)
                self.frame=render_recipe(commands,self.workspace.archives,self.workspace.projects,self.workspace.settings,bytes.fromhex(self.workspace.recipes['fill_table']),bytes.fromhex(self.workspace.recipes['mono_table']))
                if view=='Overlay inspector':
                    self.raster,_,_=overlay_inspector(commands,self.family,self.selected,self.workspace.archives,self.workspace.projects,
                        self.workspace.settings,bytes.fromhex(self.workspace.recipes['fill_table']),bytes.fromhex(self.workspace.recipes['mono_table']))
                else:self.raster=self.frame.raster()
                image=self.workspace.archives[self.family].analysis_by_id(self.selected).image
                role=next(role for rid,label,role in self.components if rid==self.selected)
                self.details.set(f'{self.family} / {self.selected}\n{resource_name(self.family,self.selected).split(" [")[0]}\n{role} • {image.width*2} × {image.height} CGA bits\nP0 placement; no dithering')
                self.status.set('Inspector: before this draw / write mask / after this draw. Later objects may cover it in the full room.' if view=='Overlay inspector' else 'Selected resource outlined in cyan. Click a visible image to edit it.')
                self.signature=signature;self.paint()
                if hasattr(self,'slotbuttons'):
                    for slot,button in self.slotbuttons.items():
                        rgb=carrier_rgb(self.workspace.settings.patterns[slot]);button.configure(bg='#%02x%02x%02x'%rgb,
                            fg='black' if sum(rgb)>360 else 'white',selectcolor='#%02x%02x%02x'%rgb)
        except (OSError,ValueError,KeyError) as exc:
            self.frame=None;self.canvas.delete('all');self.status.set(str(exc))
        self.timer=self.after(350,self.refresh)

    def paint(self):
        if self.frame is None:return
        # Integer signal pixels, with 4:3 display aspect; default 640x480.
        scale=max(1,min(self.canvas.winfo_width()//640,self.canvas.winfo_height()//480))
        width,height=640*scale,480*scale
        raw=bytearray()
        for y in range(height):
            row=self.raster.pixels[(y*200//height)*1920:(y*200//height+1)*1920]
            if scale==1:raw.extend(row)
            else:
                for x in range(640):raw.extend(row[x*3:x*3+3]*scale)
        self.photo=tk.PhotoImage(data=png_bytes(width,height,bytes(raw)))
        self.origin=(max(0,(self.canvas.winfo_width()-width)//2),max(0,(self.canvas.winfo_height()-height)//2));self.size=(width,height)
        self.canvas.delete('all');self.canvas.create_image(*self.origin,image=self.photo,anchor='nw')
        if self.viewvar.get()=='Overlay inspector':
            for i,title in enumerate(('Before overlay','Transparency mask','Combined result')):
                self.canvas.create_text(self.origin[0]+(104+216*i)*scale,self.origin[1]+32*scale,text=title,fill='white',font=('Segoe UI',10,'bold'),width=192*scale)
            self.canvas.create_text(self.origin[0]+320*scale,self.origin[1]+448*scale,text='Cyan = drawn pixels, including black. Checkerboard = transparent.',fill='#c8d4df',font=('Segoe UI',9))
        else:
            for name,rid,x,y,w,h in self.frame.hits:
                if name==self.family and rid==self.selected:
                    self.canvas.create_rectangle(self.origin[0]+x*scale,self.origin[1]+y*height/200,
                        self.origin[0]+(x+w)*scale,self.origin[1]+(y+h)*height/200,outline='#32dceb')

    def pick(self,event):
        if self.frame is None:return
        if self.viewvar.get()=='Overlay inspector':self.edit_selected();return
        x=(event.x-self.origin[0])*640//self.size[0];y=(event.y-self.origin[1])*200//self.size[1]
        picked=self.frame.pick(x,y)
        if picked:
            name,rid=picked;self.status.set(f'{name} / {rid} — {resource_name(name,rid)}')
            if name=='WALLS':
                if hasattr(self,'slotvar') and rid in SLOTS:self.slotvar.set(rid)
                return
            self.controller.edit_resource(name,rid)

    def hover(self,event):
        if self.frame is None:return
        if self.viewvar.get()=='Overlay inspector':return
        x=(event.x-self.origin[0])*640//self.size[0];y=(event.y-self.origin[1])*200//self.size[1]
        picked=self.frame.pick(x,y)
        if picked:
            name,rid=picked
            self.status.set(f'Brick fill {rid:02X} — click to select its swatch' if name=='WALLS' else f'{name} / {rid} — {resource_name(name,rid)} — click to edit')

    def export_png(self):
        if self.frame is None:return
        filename=filedialog.asksaveasfilename(parent=self,title='Export composite preview',defaultextension='.png',filetypes=[('PNG','*.png')])
        if filename:
            self.photo.write(filename,format='png')

    def close(self):
        self.after_cancel(self.timer)
        if self in self.controller.windows:self.controller.windows.remove(self)
        self.destroy()
