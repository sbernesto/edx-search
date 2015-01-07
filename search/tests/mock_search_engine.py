""" Implementation of search interface to be used for tests where ElasticSearch is unavailable """
import copy
import datetime
from numbers import Number
from search.manager import SearchEngine


def _convert_to_date(json_date_string_value):
    ''' converts json date string to date object '''
    if json_date_string_value is None:
        return None

    if json_date_string_value == "now":
        return datetime.datetime.utcnow()

    try:
        if "T" in json_date_string_value:
            if "." in json_date_string_value:
                format_string = "%Y-%m-%dT%H:%M:%S.%fZ"
            else:
                format_string = "%Y-%m-%dT%H:%M:%SZ"
        else:
            format_string = "%Y-%m-%d"

        return datetime.datetime.strptime(
            json_date_string_value,
            format_string
        )
    except ValueError:
        return None


def _null_conversion(value):
    """ no-op function, just returns what you give it """
    return value


def contains_numbers(array_of_values):
    """ True if anything value in the array is a number """
    for test_value in array_of_values:
        if isinstance(test_value, Number):
            return True
    return False


def find_field(doc, field_name):
    """ find the dictionary field corresponding to the . limited name """
    field_chain = field_name.split('.', 1)
    if len(field_chain) > 1:
        return find_field(doc[field_chain[0]], field_chain[1]) if field_chain[0] in doc else None
    else:
        return doc[field_chain[0]] if field_chain[0] in doc else None


def _filter_field_dictionary(documents_to_search, field_dictionary):
    """ remove the documents for which the fields do not match """
    filtered_documents = documents_to_search
    for field_name in field_dictionary:
        field_value = field_dictionary[field_name]
        if isinstance(field_value, list) and len(field_value) == 2:
            fn_conv = _null_conversion if contains_numbers(field_value) else _convert_to_date
            if field_value[0]:
                filtered_documents = [d for d in filtered_documents if fn_conv(
                    find_field(d, field_name)) >= fn_conv(field_value[0])]
            if field_value[1]:
                filtered_documents = [d for d in filtered_documents if fn_conv(
                    find_field(d, field_name)) <= fn_conv(field_value[1])]
        else:
            filtered_documents = [d for d in filtered_documents if find_field(d, field_name) == field_value]

    return filtered_documents


def _filter_filter_dictionary(documents_to_search, filter_dictionary):
    """ remove the documents for which the fields do not match iff the field is present """
    filtered_documents = documents_to_search
    for field_name in filter_dictionary:
        field_value = filter_dictionary[field_name]
        if isinstance(field_value, list) and len(field_value) == 2:
            fn_conv = _null_conversion if contains_numbers(field_value) else _convert_to_date
            if field_value[0]:
                filtered_documents = [d for d in filtered_documents if fn_conv(
                    find_field(d, field_name)) >= fn_conv(field_value[0]) or find_field(d, field_name) is None]
            if field_value[1]:
                filtered_documents = [d for d in filtered_documents if fn_conv(
                    find_field(d, field_name)) <= fn_conv(field_value[1]) or find_field(d, field_name) is None]
        else:
            filtered_documents = [d for d in filtered_documents if find_field(
                d, field_name) == field_value or find_field(d, field_name) is None]

    return filtered_documents


def _process_query_string(documents_to_search, search_strings):
    """ keep the documents that contain at least one of the search strings provided """
    def has_string(dictionary_object, search_string):
        """ search for string in dictionary items, look down into nested dictionaries """
        for name in dictionary_object:
            if isinstance(dictionary_object[name], dict):
                return has_string(dictionary_object[name], search_string)
            elif search_string in dictionary_object[name]:
                return True
        return False

    documents_to_keep = []
    for search_string in search_strings:
        documents_to_keep.extend([d for d in documents_to_search if has_string(d["content"], search_string)])

    return documents_to_keep


class MockSearchEngine(SearchEngine):

    """
    Mock implementation of SearchEngine for test purposes
    """
    _mock_elastic = {}

    @classmethod
    def destroy(cls):
        """ Clean out the dictionary for test resets """
        cls._mock_elastic = {}

    def __init__(self, index=None):
        super(MockSearchEngine, self).__init__(index)

    def index(self, doc_type, body, **kwargs):
        if self.index_name not in MockSearchEngine._mock_elastic:
            MockSearchEngine._mock_elastic[self.index_name] = {}

        _mock_index = MockSearchEngine._mock_elastic[self.index_name]
        if doc_type not in _mock_index:
            _mock_index[doc_type] = []

        _mock_index[doc_type].append(body)

    def remove(self, doc_type, doc_id, **kwargs):
        _mock_index = MockSearchEngine._mock_elastic[self.index_name]
        _mock_index[doc_type] = [d for d in _mock_index[doc_type] if "id" not in d or d["id"] != doc_id]

    def search(self, query_string=None, field_dictionary=None, filter_dictionary=None, **kwargs):
        documents_to_search = []
        if "doc_type" in kwargs:
            if kwargs["doc_type"] in MockSearchEngine._mock_elastic[self.index_name]:
                documents_to_search = MockSearchEngine._mock_elastic[self.index_name][kwargs["doc_type"]]
        else:
            for doc_type in MockSearchEngine._mock_elastic[self.index_name]:
                documents_to_search.extend(MockSearchEngine._mock_elastic[self.index_name][doc_type])

        if field_dictionary:
            documents_to_search = _filter_field_dictionary(documents_to_search, field_dictionary)

        if filter_dictionary:
            documents_to_search = _filter_filter_dictionary(documents_to_search, filter_dictionary)

        if query_string:
            documents_to_search = _process_query_string(documents_to_search, query_string.split(" "))

        # Finally, find duplicates and give them a higher score
        search_results = []
        max_score = 0
        while len(documents_to_search) > 0:
            current_doc = documents_to_search[0]
            score = len([d for d in documents_to_search if d == current_doc])
            if score > max_score:
                max_score = score
            documents_to_search = [d for d in documents_to_search if d != current_doc]

            data = copy.copy(current_doc)
            search_results.append(
                {
                    "score": score,
                    "data": data,
                }
            )

        return {
            "took": 10,
            "total": len(search_results),
            "max_score": max_score,
            "results": sorted(search_results, key=lambda k: k["score"])
        }
