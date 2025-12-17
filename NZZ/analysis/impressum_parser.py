import csv
from collections import defaultdict

class NZZParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self._staff_dict = defaultdict(list)
        self.parse_file()

    def parse_file(self):
        """Reads the CSV and populates the dictionary."""
        try:
            with open(self.file_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Strip whitespace to handle potential CSV formatting issues
                    name = row['Name'].strip()
                    dept = row['Department'].strip()
                    
                    # Add department to the list if it isn't already there
                    if dept not in self._staff_dict[name]:
                        self._staff_dict[name].append(dept)
        except FileNotFoundError:
            print(f"Error: The file at {self.file_path} was not found.")
        except KeyError as e:
            print(f"Error: Missing expected column in CSV: {e}")

    def get_dict(self):
        """Returns the result as a standard dictionary."""
        return dict(self._staff_dict)

    def get_departments_by_name(self, name):
        """Helper method to find departments for a specific person."""
        return self._staff_dict.get(name, "Name not found")

# --- Usage Example ---
# parser = NZZParser('nzz_data.csv')
# data = parser.get_dict()
# print(data['Ivo Mijnssen']) 
# Output: ['Chefredaktion', 'Tagesleitung']