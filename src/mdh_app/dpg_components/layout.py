# Source/Credit: https://github.com/fabriciochamon/DearPyGui_Extend
# Made some minor changes to the original code. 
# Ex: Edited dpge layout code so that the height is passed from column to the next table in loop, rather than starting at 1 every time

import logging
import random
import dearpygui.dearpygui as dpg

logger = logging.getLogger(__name__)

def add_layout(layout, **kwargs):
	"""
	A window layouting system based on a simple human readable format.

	:param str layout: A string containing the layout. Uses tab based identation syntax (More info below).
	:param int parent: The layout parent item.
	:param bool border: Displays a border around panes.
	:param bool resizable: Allow pane columns to be resized.
	:param bool debug: Displays random colors as indication for each pane.

	:returns: A Layout object. You can access the "root" class attribute to refer to the top most dpg item of the layout.

	LAYOUT - the top most item (required as the first line). Accepts 3 positional parameters: 
		- name: the main layout table tag
		- halign: horizontal alignment mode  (left | center | right)
		- valign: vertical alignment mode    (top  | center | bottom)
		
		*If defined, global layout alignment options will be used for all columns. (Any column can override this value with its own alignment parms).
	
	ROW - a row item. Accepts 1 positional parameter: 
		- size: row height as a normalized 0-1 value. (If omitted, remaining height will be automatically distributed between all the rows without this parm)
	
	COL - a column item. Accepts 4 positional parameters: 
		- name: the dpg container tag, that you can access later to put the child widgets on.
		- size: the column width as a normalized 0-1 value. (If omitted, remaining width will be automatically distributed between all the columns without this parm)
		- halign: horizontal alignment mode  (left | center | right)
		- valign: vertical alignment mode    (top  | center | bottom)

	"""
	return Layout(layout, **kwargs)

class Layout:

	# layout initialization (called from frame callback)
	def init_layout(sender, app_data, user_data):
		top_level_alias = user_data['top']
		debug = user_data['debug']
		border = user_data['border']
		resizable = user_data['resizable']

		def auto_align(item, alignment_type: int, x_align: float = 0.5, y_align: float = 0.5):
			def _center_h(_s, _d, data):
				parent = dpg.get_item_parent(data[0])
				while dpg.get_item_info(parent)['type'] != "mvAppItemType::mvChildWindow":
					parent = dpg.get_item_parent(parent)
				parentWidth = dpg.get_item_rect_size(parent)[0]
				width = dpg.get_item_rect_size(data[0])[0]
				newX = int((parentWidth - width) * data[1])
				dpg.set_item_pos(data[0], [newX, dpg.get_item_pos(data[0])[1]])

			def _center_v(_s, _d, data):
				parent = dpg.get_item_parent(data[0])
				while dpg.get_item_info(parent)['type'] != "mvAppItemType::mvChildWindow":
					parent = dpg.get_item_parent(parent)
				parentHeight = dpg.get_item_rect_size(parent)[1]
				height = dpg.get_item_rect_size(data[0])[1]
				newY = int((parentHeight - height) * data[1])
				dpg.set_item_pos(data[0], [dpg.get_item_pos(data[0])[0], newY])

			def _center_both(_s, _d, data):
				parent = dpg.get_item_parent(data[0])
				while dpg.get_item_info(parent)['type'] != "mvAppItemType::mvChildWindow":
					parent = dpg.get_item_parent(parent)
				parentWH = dpg.get_item_rect_size(parent)
				itemWH = dpg.get_item_rect_size(data[0])
				newXY = [int((parentWH[0] - itemWH[0]) * data[1]), int((parentWH[1] - itemWH[1]) * data[2])]
				dpg.set_item_pos(data[0], newXY)

			if 0 <= alignment_type <= 2:
				with dpg.item_handler_registry():
					if alignment_type == 0:
						# horizontal only alignment
						dpg.add_item_visible_handler(callback=_center_h, user_data=[item, x_align])
					elif alignment_type == 1:
						# vertical only alignment
						dpg.add_item_visible_handler(callback=_center_v, user_data=[item, y_align])
					elif alignment_type == 2:
						# both horizontal and vertical alignment
						dpg.add_item_visible_handler(callback=_center_both, user_data=[item, x_align, y_align])

				dpg.bind_item_handler_registry(item, dpg.last_container())

		def align_items(parent):
			children = dpg.get_item_children(parent, 1)
			for child in children:
				item_type = dpg.get_item_type(child)
				user_data = dpg.get_item_configuration(child)['user_data']
				if item_type=='mvAppItemType::mvGroup' and user_data is not None and isinstance(user_data, dict) and 'type' in user_data.keys() and user_data['type']=='__layout_content':
					halignments = ['left','center','right']
					valignments = ['top','center','bottom']
					values = [0, 0.5, 1]
					halign=values[halignments.index(user_data['halign'])]
					valign=values[valignments.index(user_data['valign'])]
					auto_align(child, 2, halign, valign)

				align_items(child)
				
		def configure_by_type(item):
			if dpg.get_item_type(item)=='mvAppItemType::mvTable':
				dpg.configure_item(
					item, 
					no_pad_outerX=True, 
					no_pad_innerX=True, 
					pad_outerX=False, 
					borders_innerH=False, 
					borders_outerH=False, 
					borders_innerV=False,
					borders_outerV=False,
					scrollX=False,
					scrollY=False,
					resizable=resizable,
					)
				
			if dpg.get_item_type(item)=='mvAppItemType::mvChildWindow':
				chwindow_ud = dpg.get_item_user_data(item)
				border_setting = border if (chwindow_ud and 'col_has_children' in chwindow_ud and not chwindow_ud['col_has_children']) else False
				dpg.configure_item(
					item, 
					autosize_x=True,
					no_scrollbar=False,
					border=border_setting,
					)
				align_items(item)
				
				# color window BGs
				if debug:
					theme_name = f'__layout_child_theme_{item}'
					if not dpg.does_item_exist(theme_name):
						with dpg.theme(tag=theme_name):
							random.seed(theme_name+'_R')
							r = random.random()
							random.seed(theme_name+'_G')
							g = random.random()
							random.seed(theme_name+'_B')
							b = random.random()
							with dpg.theme_component(dpg.mvChildWindow):
								dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (r*150,g*150,b*150))
					dpg.bind_item_theme(item, theme_name)
			
		def get_parent_window(item):
			parent = dpg.get_item_parent(item)
			while dpg.get_item_info(parent)['type'] != "mvAppItemType::mvWindowAppItem":
				parent = dpg.get_item_parent(parent)
			return parent 

		def adjust_layout(item):
			children = dpg.get_item_children(item, 1)
			configure_by_type(item)
			for child in children:
				user_data=dpg.get_item_configuration(child)['user_data']
				if isinstance(user_data, dict) and 'type' in user_data.keys() and user_data['type']=='__layout_item':
					dpg.configure_item(child, height=dpg.get_item_rect_size(get_parent_window(child))[1]*user_data['height'])
				adjust_layout(child)

		# main window theme
		with dpg.theme() as layout_parent_theme:
			with dpg.theme_component(dpg.mvChildWindow):
				dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
			with dpg.theme_component(dpg.mvTable):
				dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 0, 0)
		dpg.bind_item_theme(get_parent_window(top_level_alias), layout_parent_theme)

		# main window resize handler
		with dpg.item_handler_registry() as layout_parent_resize_handler:
			dpg.add_item_resize_handler(callback=lambda: adjust_layout(top_level_alias))
		dpg.bind_item_handler_registry(get_parent_window(top_level_alias), layout_parent_resize_handler)

		# adjust layout heights
		adjust_layout(top_level_alias)

	def __init__(self, layout='LAYOUT new_layout', parent=None, border=False, resizable=False, debug=False):
		self.layout=layout
		self.parent=parent
		self.debug=debug
		self.border=border
		self.resizable=resizable
		self.root=None

		# check if string can be converted to float
		def isFloat(s):
			ret=True
			try: float(s)
			except: ret=False
			return ret

		# parse string layout into a list of dicts with each layout item as an entry
		def parse_layout(layout):
			layout_list = []
			parents = [-1]
			last_level = 0
			ids = []

			for i, line in enumerate(layout.split('\n')):
				contents = line.strip()
				if len(contents):
					level = line.count('\t')
					data = line.replace('\t', '').split(' ')
					if level>last_level: parents.append(ids[-1])
					if level<last_level: 
						movement = last_level-level
						del parents[-movement:]
					id = i
					ids.append(id)			

					size = None
					if data[0]=='COL':
						if len(data)>=3:
							size = float(data[2]) if isFloat(data[2]) else None
					elif data[0]=='ROW':
						if len(data)>=2:
							size = float(data[1]) if isFloat(data[1]) else None

					tag = None
					if data[0] in ['LAYOUT', 'COL']:
						if len(data)>=2 and data[1].strip()!='':
							tag = data[1]

					halign = None
					valign = None
					if level==0:
						if len(data)>=3: halign=data[2]
						if len(data)>=4: valign=data[3]
					else:
						if len(data)>=4: halign=data[3]
						if len(data)>=5: valign=data[4]

					entry = {
						'id': id,
						'level': level,
						'parent': parents[-1],
						'type': data[0],
						'tag': tag,
						'size': size,
						'halign': halign,
						'valign': valign,
						'contents': contents,
					}
					entry['size']=None if entry['level']==0 else entry['size']
					layout_list.append(entry)
					last_level = level
			
			return layout_list

		# recursively builds the table elements
		def build_table(item, layout, parent_item=None, debug=False):

			def get_layout_item(id, layout):
				return [x for x in layout if x['id']==id][0]

			def get_subelements(id, layout, etype='col'):
				elements = [x for x in layout if x['parent']==id and x['type']==etype.upper()]
				return elements

			tag_table = None
			has_children = len([x for x in layout if x['parent']==item['id']])>0
			if has_children:
				
				# add table
				if parent_item is None:
					parent = item['parent'] if item['parent'] != -1 else dpg.last_item()
				else:
					parent = parent_item
				tag_table = item['tag'] if item['tag'] is not None else f'__layout_table_{item["id"]}'
				dpg.add_table(header_row=False, tag=tag_table, parent=parent)
				
				parent_userdata = dpg.get_item_user_data(parent)
				table_height = 1 if (not parent_userdata or not 'height' in parent_userdata) else parent_userdata['height']
				
				# add columns
				cols = get_subelements(item['id'], layout, 'col')
				has_cols = len(cols)>0
				if len(cols)==0:
					cols=[{
						'id': dpg.generate_uuid()+1000,
						'level': item['level']+1,
						'parent': item['id'],
						'type': 'COL',
						'tag': None,
						'size': 1,
						'halign': 'left',
						'valign': 'top',
						'contents': 'COL 1 left top',
					}]
				col_size_sum   = sum([x['size'] for x in cols if x['size'] is not None])
				col_no_size    = len([x for x in cols if x['size'] is None])
				col_size_split = (1-col_size_sum)/col_no_size if col_no_size>0 else 1
				for col in cols:
					tag_col = f'__layout_col_{col["id"]}'
					col_size = col['size'] if col['size'] is not None else col_size_split
					dpg.add_table_column(tag=tag_col, parent=tag_table, init_width_or_weight=col_size)

				# add rows
				rows = get_subelements(item['id'], layout, 'row')
				has_rows = len(rows)>0
				if len(rows)==0:
					rows=[{
						'id': dpg.generate_uuid()+1000,
						'level': item['level']+1,
						'parent': item['id'],
						'type': 'ROW',
						'tag': None,
						'size': table_height,
						'halign': 'left',
						'valign': 'top',
						'contents': 'ROW 1',
					}]
				row_size_sum   = sum([x['size'] for x in rows if x['size'] is not None])
				row_no_size    = len([x for x in rows if x['size'] is None])
				row_size_split = (table_height-row_size_sum)/row_no_size if row_no_size > 0 else table_height
				for row in rows:
					tag_row = f'__layout_row_{row["id"]}'
					row_size = row['size'] if row['size'] is not None else row_size_split
					dpg.add_table_row(parent=tag_table, tag=tag_row)

					for col in cols:
						tag_cw = f'__layout_cw_{row["id"]}_{col["id"]}'
						col_has_children = len(get_subelements(col['id'], layout, 'col'))>0 or len(get_subelements(col['id'], layout, 'row'))>0
						user_data_cw = '' if row['size']==1 else {'type': '__layout_item', 'height': row_size, 'col_has_children': col_has_children}
						dpg.add_child_window(tag=tag_cw, parent=tag_row, user_data=user_data_cw)
						if not col_has_children and col['tag'] is not None:
							level0 = [x for x in layout if x['level']==0][0]
							halign = col['halign']
							valign = col['valign']
							if halign is None:
								halign = level0['halign'] if level0['halign'] is not None else 'left'
							if valign is None:
								valign = level0['valign'] if level0['valign'] is not None else 'top'

							grp = dpg.add_group(tag=col['tag'], parent=tag_cw, user_data={'type': '__layout_content', 'halign': halign, 'valign': valign})
							if debug: dpg.add_text(col['tag'], parent=grp)
						build_table(col, layout, tag_cw, debug)

					if has_rows: build_table(row, layout, tag_cw, debug)

			self.root = tag_table
			
		parsedlayout = parse_layout(layout=self.layout)
		if self.parent is None: 
			self.parent=dpg.last_item()
		build_table(parsedlayout[0], parsedlayout, self.parent, self.debug)
		dpg.set_frame_callback(2, Layout.init_layout, user_data={'top': self.root, 'debug': self.debug, 'border': self.border, 'resizable': self.resizable})

