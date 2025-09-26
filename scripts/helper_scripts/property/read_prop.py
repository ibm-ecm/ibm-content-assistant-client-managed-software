###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2023. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################

import platform

import toml


class ReadProp():
    # Shared by all instances for this type of class.
    required_fields = {}

    # Recursively checks for missing/required fields
    # in tables or tables within tables
    def __recurse_check_values(self, table, key_history=[]):
        for key in table:
            # If the value is indicated as another table,
            # we recursively call this function to check for other tables
            if type(table[key]) is dict:
                # key_history is required when outputting which specific
                # field is missing to the user when using recursive calls
                self.__recurse_check_values(table[key], key_history + [key])

            elif type(table[key]) is list:
                if "<Required>" in table[key]:
                    # Create a new entry for this property file as to what fields might be
                    # split filename from path and store it in required_fields
                    if platform.system() == "Windows":
                        delimiter = "\\"
                    else:
                        delimiter = "/"
                    file_name = self._prop_filepath.split(delimiter + "propertyFile" + delimiter)[-1]

                    if file_name not in self.required_fields:
                        self.required_fields[file_name] = []
                    self.required_fields[file_name].append((key_history + [key], table[key]))

            # If the value field is not a table, we just check
            # the user has not entered or edited the fields yet
            elif table[key] == '<Required>' or table[key] == '':
                # Create a new entry for this property file as to what fields might be
                # split filename from path and store it in required_fields
                if platform.system() == "Windows":
                    delimiter = "\\"
                else:
                    delimiter = "/"
                file_name = self._prop_filepath.split(delimiter + "propertyFile" + delimiter)[-1]

                if file_name not in self.required_fields:
                    self.required_fields[file_name] = []
                self.required_fields[file_name].append((key_history + [key], table[key]))

    # Returns true if user has missed any required fields.
    def missing_required_fields(self):
        if len(self.required_fields) > 0:
            return True
        return False

    # function to read property files into dictionaries
    def __init__(self, propertyfile, logger):
        self._prop_filepath = None

        self._logger = logger
        self._prop_filepath = propertyfile
        self._toml_dict = None
        self._toml_dict = toml.loads(open(self._prop_filepath, encoding="utf-8").read())
        self.__recurse_check_values(self._toml_dict)


    def to_dict(self):
        return self._toml_dict


# ReadPropContentAssistant does additional parsing to find number of AI providers
class ReadPropContentAssistant(ReadProp):
    def __find_ai_providers_ids(self):
        # Filter for keys that start with "AI_PROVIDER"
        # and add them to the list of AI provider IDs
        ai_providers_ids = [key for key in self._toml_dict.keys() if key.startswith("AI_PROVIDER")]
        self._toml_dict["_ai_providers_ids"] = ai_providers_ids
        self._toml_dict["ai_providers_number"] = len(ai_providers_ids)
    def __init__(self, propertyfile, logger):
        super().__init__(propertyfile, logger)
        self.__find_ai_providers_ids()

# ReadPropVectorDatabase does additional parsing to find number of vector database IDs
class ReadPropVectorDatabase(ReadProp):
    def __find_vector_database_ids(self):
        vector_database_ids = list(self._toml_dict.keys())
        self._toml_dict["_vector_database_ids"] = vector_database_ids
        self._toml_dict["vector_database_number"] = len(vector_database_ids)
    def __init__(self, propertyfile, logger):
        super().__init__(propertyfile, logger)
        self.__find_vector_database_ids()

class ReadPropIngress(ReadProp):
    def __init__(self, propertyfile, logger):
        super().__init__(propertyfile, logger)

class ReadPropIdp(ReadProp):
    def __find_idp_ids(self):
        idp_ids = list(self._toml_dict.keys())
        self._toml_dict["_idp_ids"] = idp_ids
        self._toml_dict["idp_number"] = len(idp_ids)

    def __init__(self, propertyfile, logger):
        super().__init__(propertyfile, logger)
        self.__find_idp_ids()

class ReadPropDeployment(ReadProp):
    def __init__(self, propertyfile, logger):
        super().__init__(propertyfile, logger)


class ReadPropImageTag(ReadProp):
    def __init__(self, propertyfile, logger):
        super().__init__(propertyfile, logger)

    def check_toml(self):
        keys_to_check = ["TAG", "REPOSITORY", "DIGEST"]
        self._incorrect_keys_list = []
        for key, value in self._toml_dict.items():
            if set(keys_to_check).issubset(set(value.keys())):
                self._incorrect_keys_list.append(key)
        return self._incorrect_keys_list
