from xlrd import open_workbook
from matplotlib.pyplot import clf, figure, grid, hist, legend, pause, plot, scatter, show, subplot, title, xlabel, ylabel, xscale, yscale
from numpy import array, corrcoef, geomspace, hstack, inf, isnan, linspace, log10, unravel_index

class ExcelColumnNames(list):

	_translations = {
		"Number of returns with dependents" : "Number of dependents",
		"Unemployment compensation in agi" : "Unemployment compensation",
		"Social security benefits in agi" : "Taxable social security benefits",
		"Residential energy tax credit" : "Residential energy credit",
		}

	def _process_column_name(self, cell):
		#	should I run some typechecking here?
		column_name = cell.value.split("[")[0].replace("\n", " ").strip().replace("  "," ").capitalize()
		return self._translations[column_name] if column_name in self._translations else column_name

	def _column_names(self, row, year2008):
		current_column_name = str()
		# print(row)
		too_many_blank_cells = 2 - year2008
		for cell in row:
			if cell.ctype:
				blank_count = 0
				current_column_name = self._process_column_name(cell)
			else:
				blank_count += 1
			if blank_count == too_many_blank_cells:
				break
			else:
				yield current_column_name
			
	def __init__(self, *args):
		super().__init__(self._column_names(*args))
	

class ExcelColumnTypes(list):

	_special_columns = {	"Zip code" : 						"ZIP_code", 
							"Size of adjusted gross income" :	"AGI_bracket",  
							"Adjusted gross income (agi)" :		"AGI",
							"Number of returns" :				"n_returns",
							}

	@staticmethod
	def _column_subtype(column_name, column_subname): #	column_name is needed for the year 2008 version
		return "Amount" if "Amount" in column_subname.value else "Number"
		#
		#	what about "Amount of AGI" subname for itemized deductions in 2004-2006 and 2012-2015?
		
	def _column_types(self, *args):
		for column_name, column_subname in zip(*args):
			yield self._special_columns[column_name] if column_name in self._special_columns else self._column_subtype(column_name, column_subname)
			
	def pop_special_columns(self, row):
		for index in sorted((self.ZIP_code_index, self.AGI_bracket_index), reverse=True):
			row.pop(index)

	def __init__(self, column_names, column_subnames):
		#	this takes two arguments: an instance of ExcelColumnNames & the row of column subnames
		super().__init__(self._column_types(column_names, column_subnames))
		self.ZIP_code_index = self.index("ZIP_code")
		self.AGI_bracket_index = self.index("AGI_bracket")
		self.pop_special_columns(column_names)
		self.pop_special_columns(self)
		self.n_returns_index = self.index("n_returns")
		self.AGI_index = self.index("AGI")


class Year2008ExcelColumnTypes(ExcelColumnTypes):

	@staticmethod
	def _column_subtype(column_name, column_subname):
		return "Number" if "Number" in column_name else "Amount"
		
		
class AGIBracket(object):

	def __repr__(self):
		return "${:,} or more".format(self.lower) if self.upper == inf else "${:,} under ${:,}".format(*(self.lower, self.upper))

	def __hash__(self):
		return hash((self.lower, self.upper))
		
	def __eq__(self, other):
		return (self.lower, self.upper) == (other if isinstance(other, tuple) else (other.lower, other.upper))

	def __add__(self, other):
		return type(self)(min(self.lower, other.lower), max(self.upper, other.upper))		

	@staticmethod
	def _dollars_str_to_int(dollars_string):
		return inf if dollars_string == "more" else int(dollars_string.strip("$ ").replace(",", ""))

	def _parse_string(self, bracket_string):
		if bracket_string:
			limits = bracket_string.lower().split()
			if len(limits) == 2:
				result = (1, self._dollars_str_to_int(limits[1]))
			else:
				result = (self._dollars_str_to_int(limits[index]) for index in (0, 2))		
		else:
			result = (1, inf)
		return result

	def __init__(self, *args):
		super().__init__()
		self.lower, self.upper = self._parse_string(args[0]) if len(args) == 1 else args
		
		
class TaxDataRow(list):

	def __add__(self, other):
		result = TaxDataRow(sum(vals) for vals in zip(self, other))
		result.ZIP_code = self.ZIP_code
		result.AGI_bracket = self.AGI_bracket + other.AGI_bracket
		return result
		
	def __itruediv__(self, other):
		for index, normalization in enumerate(other):
			if normalization:
				self[index] /= normalization
		return self

	def apply_log10(self):
		for index, value in enumerate(self):
			self[index] = log10(value) if value > 0 else -12 - log10(-value) if value < 0 else -6
		
	def normalize(self, column_types):
		n_returns, AGI = (self[index] for index in (column_types.n_returns_index, column_types.AGI_index))
		# print(f"\t{self.ZIP_code}: {n_returns} returns, AGI {AGI}")
		# print(f"\t{self.ZIP_code} {len(self)} in self, {len(column_types)} in column_types")
		prio_col_type = None
		for index, col_type in enumerate(column_types):
			#	Amount / Number for the same line item normalization
			if col_type == "Amount" and prior_col_type == "Number" and self[index - 1]:
				self[index] /= self[index - 1]
			prior_col_type = col_type
			#	AGI-bracket-wide normalization
			normalization = n_returns if col_type in ("Number", "AGI") else AGI if col_type == "Amount" else None
			if normalization:
				try:
					self[index] /= normalization
				except IndexError:
					print(f"\tnormalization problem for {self.ZIP_code}")
					print(f"\t{len(column_types)} {column_types}")
					raise IndexError
#			elif normalization == 0:
#				self[index] = float("nan")

class ExcelDataRow(TaxDataRow):

	def _parse_cells(self, row, column_types):
		# any row without an AGI or a valid ZIP code will result in an empty list
		ZIP_code_cell = row[column_types.ZIP_code_index]
		if row[column_types.AGI_index].ctype and ZIP_code_cell.ctype == 2 and ZIP_code_cell.value not in (0, 99999):
			self.AGI_bracket = AGIBracket(row[column_types.AGI_bracket_index].value)
			try:
				self.ZIP_code = int(0.5 + ZIP_code_cell.value)
			except TypeError:
				print(f"\tfailed ZIP code: {ZIP_code}")
			column_types.pop_special_columns(row)
			for cell, col_type in zip(row, column_types):
				if col_type not in ("ZIP_code", "AGI_bracket"):
					yield cell.value if cell.ctype == 2 else 0
					
	def __init__(self, *args):
		super().__init__(self._parse_cells(*args))


class ExcelDataForZIPCode(dict):

	def merge_AGI_brackets(self, first_bracket, second_bracket):
		result = self.pop(first_bracket) + self.pop(second_bracket)
		self[result.AGI_bracket] = result

	def normalize(self, column_types, total_bracket=(1, inf)):
		for row in self.values():
			row.normalize(column_types)
		if total_bracket in self:
			normalization = self[total_bracket]
			for bracket in self:
				if bracket != total_bracket:
					self[bracket] /= normalization
			#	Amount refunded in 2008 is listed as a negative number
			self[total_bracket][-1] = abs(self[total_bracket][-1])
			
	def __init__(self, rows, column_types, normalize=False, use_log10=False, **keywords):
		current_row = ExcelDataRow(next(rows), column_types)
		while current_row:
			self[current_row.AGI_bracket] = current_row
			self.ZIP_code = current_row.ZIP_code
			current_row = ExcelDataRow(next(rows), column_types)
		if (1, 10000) in self and (10000, 25000) in self:
			self.merge_AGI_brackets((1, 10000), (10000, 25000))
		if normalize:
			self.normalize(column_types, **keywords)
		if use_log10:
			for bracket in self:
				self[bracket].apply_log10()	


class ExcelDataForYear(dict):

	state_abbreviations = ('al', 'ak', 'az', 'ar', 'ca', 'co', 'ct', 'de', 'dc', 'fl', 'ga', 'hi', 'id', 'il', 'in', 'ia', 'ks', 'ky', 'la', 'me', 'md', 'ma', 'mi', 'mn', 'ms', 'mo', 'mt', 'ne', 'nv', 'nh', 'nj', 'nm', 'ny', 'nc', 'nd', 'oh', 'ok', 'or', 'pa', 'ri', 'sc', 'sd', 'tn', 'tx', 'ut', 'vt', 'va', 'wa', 'wv', 'wi', 'wy')
	
	def _post_2007_filenames(self, year, states=None):
		year = str(year)[-2:]
		formatted = "{}zp{:02}{}".format
		if states is None:
			for index, state_name in enumerate(self.state_abbreviations, 1):
				yield formatted(year, index, state_name) 
		else:
			state_names = (states.lower(),) if isinstance(states, str) else (state_name.lower() for state_name in states)
			for state_name in state_names:
				yield formatted(year, 1 + self.state_abbreviations.index(state_name), state_name)

	def _pre_2008_filenames(self, year, states=None):
		for state_name in self.state_abbreviations if states is None else (states,) if isinstance(states, str) else states:
			yield f"ZIP Code {year} {state_name.upper()}"
				
	def _read_spreadsheet(self, year, directory="/scratch/matt/irs/byZIP", **keywords):
		slash = str() if directory.endswith("/") else "/"
		for filename in (self._post_2007_filenames if year > 2007 else self._pre_2008_filenames)(year, **keywords):
			print(f"\treading {filename} . . . ", end="\r")
			yield from open_workbook(f"{directory}{slash}{filename}.xls").sheets()[0].get_rows()
		# print(str())

	@staticmethod
	def _find_headers(rows):
		for row in rows:
			if row[10].ctype:
				return row
				
	def _construct_batches(self, rows, use_log10=False, **keywords):
		self.log10_used = use_log10
		while True:
			current_batch = ExcelDataForZIPCode(rows, self.column_types, use_log10=use_log10, **keywords)
			if current_batch:
				yield current_batch.ZIP_code, current_batch	 
				
	def __init__(self, year, states=None, directory="/scratch/matt/irs/byZIP", **keywords):
		self.year = year
		rows = self._read_spreadsheet(year, directory=directory, states=states)
		self.column_names = ExcelColumnNames(self._find_headers(rows), year == 2008) 
		self.column_types = (Year2008ExcelColumnTypes if year==2008 else ExcelColumnTypes)(self.column_names, next(rows))
		for i in range(-1, year < 2009):
			next(rows) #	skip useless remaining rows in header
		super().__init__(self._construct_batches(rows, **keywords))
		

class TaxData(list):

	def histograms(self, n_bins=400):
		for line_item, column_name, column_type in zip(self, self.column_names, self.column_types):
			with Fig(0, clear=True, log_y=True, title=f"{self.year} {column_name} ({column_type})"):#, log_x=True):
				for AGI_bracket, values in line_item.items():
					# bins = geomspace(min(values), max(values), n_bins)
					bins = n_bins
					values = tuple(value for value in values if not isnan(value))
					hist(values, bins=bins, histtype="step", linewidth=4, alpha=0.3, label=str(AGI_bracket).replace("$","\\$"))
			keystrokes = input("\tPress Enter to move to the next histogram or 'q'+Enter to end: \r")
			if keystrokes.startswith("q"):
				break

	def _filter_ZIP_codes(self, batches, ZIP_codes, min_n_returns):
		self.ZIP_codes = tuple(batches.keys()) if ZIP_codes is None else (ZIP_codes,) if isinstance(ZIP_codes, int) else ZIP_codes
		if min_n_returns:
			if self.log10_used:
				min_n_returns = log10(min_n_returns)
			print(f"\tfiltering ZIP_codes . . .", end="\r")
			self.ZIP_codes = tuple(ZIP_code for ZIP_code in self.ZIP_codes if batches[ZIP_code][1, inf][self.column_types.n_returns_index] >= min_n_returns)

	def _populate_ZIP_codes(self, batches):
		n_ZIP_codes = len(self.ZIP_codes)
		for count, ZIP_code in enumerate(self.ZIP_codes, 1):
			print(f"\tpopulating ZIP code {ZIP_code} ( {count} / {n_ZIP_codes} ) . . .", end="\r")
			for AGI_bracket, line_items in batches[ZIP_code].items():
				for destination, line_item in zip(self, line_items):
					destination[AGI_bracket].append(line_item)	

	def __init__(self, year_or_by_year, ZIP_codes=None, min_n_returns=None, **keywords):
		batches = ExcelDataForYear(year_or_by_year, **keywords) if isinstance(year_or_by_year, int) else year_or_by_year
		for attribute in ("year", "column_names", "column_types", "log10_used"):
			setattr(self, attribute, getattr(batches, attribute))
		self._filter_ZIP_codes(batches, ZIP_codes, min_n_returns)
		first_batch = batches[self.ZIP_codes[0]]
		print(f"\tbuilding TaxData object . . .", end="\r")
		super().__init__(dict((AGI_bracket, list()) for AGI_bracket in first_batch.keys()) for line_item in next(iter(first_batch.values())))
		self._populate_ZIP_codes(batches)


class ColumnDetails(dict):

	def __repr__(self):
		return " ".join(repr(value) for value in self.values())


class ColumnDetailsList(list):

	def other_year(self, year):
		result = type(self)(details.copy() for details in self)
		for details in result:
			details["year"] = year
		return result
		

class FlattenedTaxData(object):

	def __getitem__(self, key):
		if isinstance(key, ColumnDetailsList):
			result = type(self)(self)
			result.data = self.data[:,tuple(self.column_details.index(details) for details in key)]
			result.column_details = key
		else:
			result = self.data[(self.ZIP_codes if isinstance(key, int) else self.column_details).index(key)]		
		return result

	def _check_columns(self, data, omit_empty=True):
		self.column_details = ColumnDetailsList()
		zero = -6 if data.log10_used else 0
		n_columns = len(data)
		for count, (line_item, column_name, column_type) in enumerate(zip(data, data.column_names, data.column_types), 1):
			# print(f"\tchecking {column_name} ({column_type}) ( {count} / {n_columns} ) . . .", end="\r")
			for AGI_bracket, values in line_item.items():
				if not omit_empty or any(not isnan(value) and value != zero for value in values):
					self.column_details.append(ColumnDetails(year=data.year, name=column_name, coltype=column_type, bracket=AGI_bracket))
					yield values
					
	def correlation_spectrum(self, label=str(), n_bins=100, square=False, figure_number=1):
		x_label = "correlation coefficient $r{}$".format("^{2}" if square else str())
		with Fig(figure_number, clear=False, log_x=False, log_y=False, x_label=x_label, y_label="number of feature pairs"):
			r = corrcoef(self.data, rowvar=False)
			lower_triangle = hstack(r[i][:i] for i in range(r.shape[1]))
			if square:
				hist(lower_triangle ** 2, bins=linspace(0, 1, n_bins), histtype="step", linewidth=3, alpha=0.4, label=label)
				# hist(lower_triangle ** 2, bins=geomspace(1e-9, 1, n_bins), histtype="step", linewidth=3, alpha=0.4, label=label) 
			else:
				hist(lower_triangle, bins=linspace(-1, 1, n_bins), histtype="step", linewidth=3, alpha=0.4, label=label) 
			grid(True, alpha=0.3, axis="x")

	def __init__(self, data, **keywords):
		super().__init__()
		self.ZIP_codes = data.ZIP_codes
		if isinstance(data, FlattenedTaxData):
			self.column_details = data.column_details
			self.data = data.data
		else:
			self.data = array(tuple(self._check_columns(data, **keywords))).transpose()
		
		
class CorrelationMatrix(object):

	column_type_priorities = ("n_returns", "AGI", "Amount", "Number")
	
	def _visible(self):
		return self.values[:self.size, :self.size]
	
	def __getitem__(self, key):
		return self._visible().__getitem__(key)

	def __setitem__(self, key, value):
		return self._visible().__setitem__(key, value)

	def drop_row_and_column(self, index):
		#	avoid creating a new matrix each time rows and columns are dropped
		if abs(index) > self.size - 1:
			raise IndexError()
		if index < 0:
			index += self.size
		old_slice = slice(index + 1, self.size)
		self.size -= 1
		new_slice = slice(index, self.size)
		self.values[new_slice] = self.values[old_slice]
		self.values[:, new_slice] = self.values[:, old_slice]
		if hasattr(self, "column_details"):
			self.column_details.pop(index)

	def drop_nan(self):
		for index in range(self.size - 1, -1, -1):
			if all(isnan(self[index])):
				# print(f"\t{self.column_names[index]} is entirely nan, dropping.")
				self.drop_row_and_column(index)

	def zero_diagonal(self): #	to allow argmax to find off-diagonal elements
		for index in range(self.size):
			self.values[index, index] = 0
			
	def max_corr(self):
		indices = unravel_index(self._visible().argmax(), (self.size,) * 2)
		return (self.values[indices], *indices)

	def histogram(self, bins=20):
		with Fig(2, clear=True, x_label="$r^{2}$", y_label="number of pairs of features"):
			for_plotting = self._visible() ** 2
			hist(for_plotting.flatten(), bins=bins)

	def filter(self):
		preferences = list()
		keep_going = True
		while keep_going:
			r2, first, second = self.max_corr()
			first_details, second_details = (self.column_details[entry] for entry in (first, second))
			if self.column_type_priorities.index(first_details["coltype"]) < self.column_type_priorities.index(second_details["coltype"]):
				keystroke = "2"
			elif self.column_type_priorities.index(first_details["coltype"]) > self.column_type_priorities.index(second_details["coltype"]):
				keystroke = "1"
			elif first_details["bracket"] == (1, inf) and second_details["bracket"] != (1, inf):
				keystroke = "2"
			elif first_details["bracket"] != (1, inf) and second_details["bracket"] == (1, inf):
				keystroke = "1"
			elif (first_details["name"], second_details["name"]) in preferences:
				keystroke = "2"
			elif (second_details["name"], first_details["name"]) in preferences:
				keystroke = "1"
			else:
				with Fig(3, clear=True, x_label=repr(first_details).replace("$", "\\$"), y_label=repr(second_details).replace("$", "\\$")):
					scatter(self.original_data[first_details], self.original_data[second_details], s=6, alpha=0.2)
				keystroke = input("\t{:.4f}\t1. {}\t2. {}\tDrop which? ".format(r2, first_details, second_details))
				if keystroke in ("1", "2"):
					names = (second_details["name"], first_details["name"]) if keystroke == "1" else (first_details["name"], second_details["name"])
					if names[0] != names[1] and names not in preferences:
						preferences.append(names)
			keep_going = keystroke in ("1", "2")
			if keep_going:
				self.drop_row_and_column(first if keystroke == "1" else second)					

	def __init__(self, data):
		super().__init__()
		self.original_data = data
		self.values = corrcoef(data.data, rowvar=False) ** 2
		self.size = self.values.shape[0]
		self.column_details = data.column_details.copy()
		self.drop_nan()
		self.zero_diagonal()
		
		
class Fig(object):
	
	def __enter__(self):
		fig = figure(self.figure_number)
		if self.clear:
			clf()
		xscale("log" if self.log_x else "linear")
		yscale("log" if self.log_y else "linear")
		return fig 
			
	def __exit__(self, *args):
		legend()
		if self.x_label:
			xlabel(self.x_label)
		if self.y_label:
			ylabel(self.y_label)
		if self.title:
			title(self.title)
		show(block=False)
		
	def __init__(self, figure_number, **keywords):
		self.figure_number = figure_number
		for attr in ("clear", "log_x", "log_y", "x_label", "y_label", "title"):
			setattr(self, attr, keywords[attr] if attr in keywords else None)
