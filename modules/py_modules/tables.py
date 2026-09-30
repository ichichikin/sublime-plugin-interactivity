# This file is a part of Interactivity plugin

try:
	import pandas as pd
except ModuleNotFoundError as e:
	if e.name != 'pandas':
		raise
	raise ImportError("the pandas library is required (pip install pandas)") from None
try:
	from tabulate import tabulate
except ModuleNotFoundError as e:
	if e.name != 'tabulate':
		raise
	raise ImportError("the tabulate library is required (pip install tabulate)") from None


# prints an Excel table (.xlsx files also need openpyxl: pip install openpyxl)
def excel_table(path: str, *args, **kwargs) -> None:
	try:
		sheets = pd.read_excel(path, *args, **kwargs)
		# several sheets (sheet_name=None or a list) come as a dict
		if isinstance(sheets, dict):
			tables = ['{}:\n\n{}'.format(name, tabulate(df, headers='keys', tablefmt='pipe')) for name, df in sheets.items()]
		else:
			tables = [tabulate(sheets, headers='keys', tablefmt='pipe')]
	except Exception as e:
		print('Unable to load the table: {}\n'.format(e))
		return
	for markdown_table in tables:
		print(f'\n{markdown_table}\n')

# prints a CSV table
def csv_table(path: str, *args, **kwargs) -> None:
	# the second argument is the separator (pandas 2 only takes it as a keyword argument)
	if args:
		kwargs.setdefault('sep', args[0])
		args = args[1:]
	try:
		df = pd.read_csv(path, *args, **kwargs)
		markdown_table = tabulate(df, headers='keys', tablefmt='pipe')
	except Exception as e:
		print('Unable to load the table: {}\n'.format(e))
		return
	print(f'\n{markdown_table}\n')
