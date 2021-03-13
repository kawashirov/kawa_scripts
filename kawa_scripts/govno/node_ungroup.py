# THIS IS COPY PASTA FROM:
# https://github.com/danielenger/Principled-Baker/blob/master/nodes/duplicate.py
# https://github.com/danielenger/Principled-Baker/blob/master/nodes/socket_index.py
# https://github.com/danielenger/Principled-Baker/blob/master/nodes/ungroup.py
#

def duplicate_node(mat, node):
	node_type = str(type(node)).split('.')[-1][:-2]
	new_node = mat.node_tree.nodes.new(type=node_type)
	
	# copy attributes
	for attr in dir(node):
		try:
			a = getattr(node, attr)
			setattr(new_node, attr, a)
		except AttributeError:
			pass
	
	# Color Ramp
	if node.type == 'VALTORGB':
		for attr in dir(node.color_ramp):
			try:
				a = getattr(node.color_ramp, attr)
				setattr(new_node.color_ramp, attr, a)
			except AttributeError:
				pass
		
		for i, col_ramp_elem in enumerate(node.color_ramp.elements):
			try:
				new_node.color_ramp.elements[i].color = col_ramp_elem.color
				new_node.color_ramp.elements[i].position = col_ramp_elem.position
			except IndexError:
				pos = col_ramp_elem.position
				new_elem = new_node.color_ramp.elements.new(pos)
				new_elem.color = col_ramp_elem.color
	
	# Curve
	if node.type == 'CURVE_RGB':
		for attr in dir(node.mapping):
			try:
				a = getattr(node.mapping, attr)
				setattr(new_node.mapping, attr, a)
			except AttributeError:
				pass
		
		# copy every point in every curve
		for i, curve in enumerate(node.mapping.curves):
			for j, point in enumerate(curve.points):
				try:
					new_node.mapping.curves[i].points[j].location = point.location
					new_node.mapping.curves[i].points[j].handle_type = point.handle_type
				except IndexError:
					pos = point.location[0]
					val = point.location[1]
					new_node.mapping.curves[i].points.new(pos, val)
	
	# copy values inputs
	for i, input in enumerate(node.inputs):
		try:
			new_node.inputs[i].default_value = input.default_value
		except:
			pass
	
	# copy values outputs
	for i, output in enumerate(node.outputs):
		try:
			new_node.outputs[i].default_value = output.default_value
		except:
			pass
	
	return new_node


def socket_index(socket):
	node = socket.node
	sockets = node.outputs if socket.is_output else node.inputs
	for i, s in enumerate(sockets):
		if s.is_linked:
			if socket == s:
				return i


def ungroup_nodes(mat, group_nodes, do_ungroup_values=True):
	new_nodes = {}
	val_nodes = []
	
	def duplicate_from_input_socket(mat, input_socket, link_to_socket):
		if not input_socket:
			return
		old_node = input_socket.links[0].from_node
		old_from_socket = input_socket.links[0].from_socket
		if old_node.type == 'GROUP_INPUT':
			# link
			index_in = socket_index(old_from_socket)
			if group_node.inputs[index_in].is_linked:
				from_socket = group_node.inputs[index_in].links[0].from_socket
				to_socket = link_to_socket
				mat.node_tree.links.new(from_socket, to_socket)
			return
		
		# create new node or take existing
		index_out = socket_index(old_from_socket)
		if old_node in new_nodes.keys():
			new_node = new_nodes[old_node]
			# link
			from_socket = new_node.outputs[index_out]
			to_socket = link_to_socket
			mat.node_tree.links.new(from_socket, to_socket)
			return
		else:
			new_node = duplicate_node(mat, old_node)
			new_nodes[old_node] = new_node
			# link
			from_socket = new_node.outputs[index_out]
			to_socket = link_to_socket
			mat.node_tree.links.new(from_socket, to_socket)
			
			for input_socket in old_node.inputs:
				if input_socket.is_linked:
					index_in = socket_index(input_socket)
					link_to_socket = new_node.inputs[index_in]
					duplicate_from_input_socket(
						mat, input_socket, link_to_socket)
	
	for group_node in group_nodes:
		if group_node.type == 'GROUP':
			# group_input_outputs
			group_input_nodes = [
				n for n in group_node.node_tree.nodes if n.type == 'GROUP_INPUT']
			output_count = len(group_input_nodes[0].outputs)
			group_input_outputs = [None] * output_count
			for node in group_input_nodes:
				for i, output in enumerate(node.outputs):
					if output.is_linked:
						group_input_outputs[i] = output
			
			# # group_output_inputs
			# group_output_nodes = [
			# 	n for n in group_node.node_tree.nodes if n.type == 'GROUP_OUTPUT']
			# input_count = len(group_output_nodes[0].inputs)
			# group_output_inputs = [None] * input_count
			# for node in group_output_nodes:
			# 	for i, input in enumerate(node.inputs):
			# 		if input.is_linked:
			# 			group_output_inputs[i] = input
			
			# new value nodes
			if do_ungroup_values:
				for index, input in enumerate(group_node.inputs):
					if group_input_outputs[index]:
						if not input.is_linked:
							val = input.default_value
							tmp_node = None
							if input.type == 'VALUE':
								tmp_node = mat.node_tree.nodes.new(
									type="ShaderNodeValue")
								tmp_node.outputs[0].default_value = val
							elif input.type == 'RGBA':
								tmp_node = mat.node_tree.nodes.new(
									type="ShaderNodeRGB")
								tmp_node.outputs[0].default_value = val
							if tmp_node:
								val_nodes.append(tmp_node)
								from_socket = tmp_node.outputs[0]
								to_socket = input
								mat.node_tree.links.new(from_socket, to_socket)
			
			# # for output in group_node.outputs:
			# 	if output.is_linked:
			# 		index = socket_index(output)
			# 		input_socket = group_output_inputs[index]
			# 		to_sockets = [
			# 			link.to_socket for link in group_node.outputs[index].links]
			# 		for link_to_socket in to_sockets:
			# 			duplicate_from_input_socket(
			# 				mat, input_socket, link_to_socket)
			
			# delete group node
			mat.node_tree.nodes.remove(group_node)
	
	# remove non linked value nodes
	for node in val_nodes:
		if not node.outputs[0].is_linked:
			mat.node_tree.nodes.remove(node)
			val_nodes.remove(node)
	
	return list(new_nodes.values()) + val_nodes
