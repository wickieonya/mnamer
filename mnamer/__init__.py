#!/usr/bin/env python3

"""
  _  _  _    _  _    __,   _  _  _    _   ,_
 / |/ |/ |  / |/ |  /  |  / |/ |/ |  |/  /  |
   |  |  |_/  |  |_/\_/|_/  |  |  |_/|__/   |_/

mnamer (Media reNAMER) is an intelligent and highly configurable media
organization utility. It parses media filenames for metadata, searches the web
to fill in the blanks, and then renames and moves them.

See https://github.com/jkwill87/mnamer for more information.
"""

import json
from argparse import ArgumentParser
from os import environ
from pathlib import Path
from re import sub
from shutil import move as shutil_move
from string import Template
from typing import List, Union, Optional, Dict, Any
from unicodedata import normalize

from appdirs import user_config_dir
from guessit import guessit
from mapi.exceptions import MapiNotFoundException
from mapi.metadata import Metadata, MetadataMovie, MetadataTelevision
from mapi.providers import Provider, provider_factory
from termcolor import cprint


def get_parameters():
    """ Retrieves program arguments from CLI parameters
    """

    help_usage = 'mnamer target [targets ...] [options] [directives]'

    help_options = '''
OPTIONS:
    mnamer attempts to load options from mnamer.json in the user's configuration
    directory, .mnamer.json in the current working directory, and then from the
    command line-- overriding each other also in that order.
    
    -b, --batch: batch mode; disables interactive prompts
    -d, --dots: format using dots in place of whitespace when renaming
    -d, --lower: format using lowercase when renaming
    -r, --recurse: show this help message and exit
    -v, --verbose: increases output verbosity
    --max_hits <number>: limits the maximum number of hits for each query
    --extension_mask <ext,...>: define extension mask used by the file parser
    --movie_api {imdb,tmdb}: set movie api provider
    --movie_destination <path>: set movie relocation destination
    --movie_template <template>: set movie renaming template
    --television_api {tvdb}: set television api provider
    --television_destination <path>: set television relocation destination
    --television_template <template>: set television renaming template'''

    help_directives = '''
DIRECTIVES:
    Whereas options configure how mnamer works, directives are one-off
    parameters that are used to perform secondary tasks like exporting the
    current option set to a file.
    
    --help: print this message and exit
    --test_run: set movie api provider
    --config_load < path >: import configuration from file
    --config_save < path >: save configuration to file
    --id < id >: explicitly specify movie or series id
    --media { movie, television }: override media detection'''

    directive_keys = {
        'id',
        'media',
        'config_save',
        'config_load',
        'test_run'
    }

    defaults = {

        # General Options
        'batch': False,
        'dots': False,  # TODO: test
        'extension_mask': [
            'avi',
            'm4v',
            'mp4',
            'mkv',
            'ts',
            'wmv',
        ],
        'lower': False,  # TODO: test
        'max_hits': 15,
        'recurse': False,
        'verbose': False,

        # Movie related
        'movie_api': 'tmdb',
        'movie_destination': '',
        'movie_template': (
            '<$title >'
            '<($year)>/'
            '<$title >'
            '<($year)>'
            '<$extension>'
        ),

        # Television related
        'television_api': 'tvdb',
        'television_destination': '',
        'television_template': (
            '<$series/>'
            '<$series - >'
            '< - S$season>'
            '<E$episode - >'
            '< - $title>'
            '<$extension>'
        ),

        # API Keys -- consider using your own or IMDb if limits are hit
        'api_key_tmdb': 'db972a607f2760bb19ff8bb34074b4c7',
        'api_key_tvdb': 'E69C7A2CEF2F3152'
    }

    parser = ArgumentParser(
        prog='mnamer', add_help=False,
        epilog='visit https://github.com/jkwill87/mnamer for more info',
        usage=help_usage
    )

    # Target Parameters
    parser.add_argument('targets', nargs='*', default=[])

    # Configuration Parameters
    parser.add_argument('-b', '--batch', action='store_true', default=None)
    parser.add_argument('-d', '--dots', action='store_true', default=None)
    parser.add_argument('-l', '--lower', action='store_true', default=None)
    parser.add_argument('-r', '--recurse', action='store_true', default=None)
    parser.add_argument('-v', '--verbose', action='store_true', default=None)
    parser.add_argument('--max_hits', type=int, default=None)
    parser.add_argument('--extension_mask', nargs='+', default=None)
    parser.add_argument('--movie_api', choices=['imdb', 'tmdb'], default=None)
    parser.add_argument('--movie_destination', default=None)
    parser.add_argument('--movie_template', default=None)
    parser.add_argument('--television_api', choices=['tvdb'], default=None)
    parser.add_argument('--television_destination', default=None)
    parser.add_argument('--television_template', default=None)

    # Directive Parameters
    # parser.add_argument('--help', action='store_true')
    parser.add_argument('--id')
    parser.add_argument('--media', choices=['movie', 'television'])
    parser.add_argument('--config_save', default=None)
    parser.add_argument('--config_load', default=None)
    parser.add_argument('--test_run', action='store_true')

    arguments = vars(parser.parse_args())
    targets = arguments.pop('targets')
    directives = {key: arguments.pop(key, None) for key in directive_keys}
    options = {
        **defaults,
        **{k: v for k, v in arguments.items() if v is not None}
    }

    # Exit early if user ask for usage help
    if 'help' in arguments:
        print(f'\nUSAGE:\n    {help_usage}\n{help_options}\n{help_directives}')
        exit(0)

    return targets, options, directives


def config_load(path: str):
    """ Reads JSON file and overlays parsed values over current configs
    """
    t = Template(path).substitute(environ)
    with open(file=t, mode='r') as fp:
        return json.load(fp)


def config_save(path: str, options: Dict[str, Any]):
    """ Serializes Config object as a JSON file
    """
    t = Template(path).substitute(environ)
    with open(file=t, mode='w') as fp:
        json.dump(options, fp, indent=4)


def dir_crawl(targets: Union[str, List[str]], **options) -> List[Path]:
    if not isinstance(targets, (list, tuple)):
        targets = [targets]
    recurse = options.get('recurse', False)
    ext_mask = options.get('extension_mask', None)
    blacklist = options.get('blacklist', {'sample', 'rarbg'})
    files = list()
    for target in targets:
        path = Path(target)
        if not path.exists():
            continue
        for file in dir_scan(path, recurse):
            if ext_mask and file.suffix.strip('.') not in ext_mask:
                continue
            if any(word in file.stem.lower() for word in blacklist):
                continue
            files.append(file.resolve())
    seen = set()
    seen_add = seen.add
    return [Path(f).absolute() for f in files if not (f in seen or seen_add(f))]


def dir_scan(path: Path, recurse=False):
    if path.is_file():
        yield path
    elif path.is_dir() and not path.is_symlink():
        for child in path.iterdir():
            if child.is_file():
                yield child
            elif recurse and child.is_dir() and not child.is_symlink():
                yield from dir_scan(child, True)


def search(metadata: Metadata, **options) -> Metadata:
    media = metadata['media']
    if not hasattr(search, "providers"):
        search.providers: List[Provider] = {}
    if media not in search.providers:
        api = {
            'television': options.get('television_api'),
            'movie': options.get('movie_api')
        }.get(media)
        keys = {
            'tmdb': options.get('api_key_tmdb'),
            'tvdb': options.get('api_key_tvdb'),
            'imdb': None
        }
        search.providers[media] = provider_factory(api, api_key=keys.get(api))
    yield from search.providers[media].search(**metadata)


def meta_parse(path: Path, media: Optional[str] = None) -> Metadata:
    abs_path_str = str(path.resolve())
    data = dict(guessit(abs_path_str, {'type': media}))

    # Parse movie metadata
    if data.get('type') == 'movie':
        meta = MetadataMovie()
        if 'title' in data:
            meta['title'] = data['title']
        if 'year' in data:
            meta['date'] = f"{data['year']}-01-01"
        meta['media'] = 'movie'

    # Parse television metadata
    elif data.get('type') == 'episode':
        meta = MetadataTelevision()
        if 'title' in data:
            meta['series'] = data['title']
        if 'season' in data:  # TODO: parse airdate
            meta['season'] = str(data['season'])
        if 'episode' in data:
            if isinstance(data['episode'], (list, tuple)):
                meta['episode'] = str(sorted(data['episode'])[0])
            else:
                meta['episode'] = str(data['episode'])
    else:
        raise ValueError('Could not determine media type')

    # Parse non-media specific fields
    quality_fields = [
        field for field in data if field in [
            'audio_profile',
            'screen_size',
            'video_codec',
            'video_profile'
        ]
    ]
    for field in quality_fields:
        if 'quality' not in meta:
            meta['quality'] = data[field]
        else:
            meta['quality'] += ' ' + data[field]
    if 'release_group' in data:
        meta['group'] = data['release_group']
    if path.suffix:
        meta['extension'] = path.suffix
    return meta


def create_path(meta: Metadata, template: str, lower=False, dots=False) -> str:
    replacements = {'&': 'and'}
    whitelist = r'[^ \d\w\?!\.,_\(\)\[\]\-/]'
    whitespace = r'[\-_\[\]]'
    text = meta.format(template)

    # Replace or remove non-utf8 characters
    text = normalize('NFKD', text)
    text.encode('ascii', 'ignore')
    text = sub(whitelist, '', text)
    text = sub(whitespace, ' ', text)

    # Replace words found in replacement list
    for replacement in replacements:
        text = text.replace(replacement, replacements[replacement])

    # Simplify whitespace
    text = sub(r'\s+', '.' if dots else ' ', text).strip()

    return text.lower() if lower else text


def move(path: Path, meta: Metadata, **options) -> Path:
    destination = options.get(f"{meta['media']}_destination")
    template = options.get(f"{meta['media']}_template")
    lower = options.get('lower', False)
    dots = options.get('dots', False)
    if isinstance(destination, str):
        destination = Path(destination)
    directory_path = destination or Path(path.parent)
    file_path = create_path(meta, template, lower, dots)
    destination_path = Path(directory_path / file_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil_move(str(path), str(destination_path))
    return destination_path


def main():
    # Initialize; load configuration and detect file(s)
    cprint('Starting mnamer', attrs=['bold'])
    targets, options, directives = get_parameters()
    config_file_paths = [
        user_config_dir() + 'mnamer.json',
        '.mnamer.conf',

    ]
    if directives.get('config_load'):
        config_file_paths.append(directives['config_load'])
    for file in config_file_paths:
        try:
            options = {**config_load(file), **options}
            print(f'success loading config from {file}')
        except IOError:
            if options.get('verbose') is True:
                print(f'error loading config from {file} (file error)')
        except ValueError:
            if options.get('verbose') is True:
                print(f'error loading config from {file} (value error)')

    # # Save config to file if requested
    # if directives.get('config_save'):
    #     print(f"Saving to {directives['config_save']}... ", end='')
    #     try:
    #         config_save(directives['config_save'], options)
    #         cprint('success!', 'green')
    #     except (IOError, KeyError, ValueError) as e:
    #         cprint(e, 'red')

    # Display config information
    if options['verbose'] is True:
        for key, value in options.items():
            print(f"  - {key}: {None if value == '' else value}")

    # Begin processing files
    detection_count = 0
    success_count = 0
    for file in dir_crawl(targets, **options):
        meta = meta_parse(file, options.get('media'))
        cprint(f'\nDetected File', attrs=['bold'])
        print(file.name)
        detection_count += 1

        # Print metadata fields
        if options['verbose'] is True:
            for field, value in meta.items():
                print(f'  - {field}: {value}')

        # Print search results
        cprint('\nQuery Results', attrs=['bold'])
        results = search(meta, **options)
        i = 1
        hits = []
        max_hits = int(options.get('max_hits'))
        while i < max_hits:
            try:
                hit = next(results)
                print(f"  [{i}] {hit}")
                hits.append(hit)
                i += 1
            except (StopIteration, MapiNotFoundException):
                break

        # Skip hit if no hits
        if not hits:
            cprint('  - None found! Skipping.', 'yellow')
            continue

        # Select first if batch
        if options['batch'] is True:
            meta.update(hits[0])

        # Prompt user for input
        else:
            print('  [RETURN] for default, [s]kip, [q]uit')
            abort = skip = None
            while True:
                selection = input('  > Your Choice? ')

                # Catch default selection
                if not selection:
                    meta.update(hits[0])
                    break

                # Catch skip hit (just break w/o changes)
                elif selection in ['s', 'S', 'skip', 'SKIP']:
                    skip = True
                    break

                # Quit (abort and exit)
                elif selection in ['q', 'Q', 'quit', 'QUIT']:
                    abort = True
                    break

                # Catch result choice within presented range
                elif selection.isdigit() and 0 < int(selection) < len(hits) + 1:
                    meta.update(hits[int(selection) - 1])
                    break

                # Re-prompt if user input is invalid wrt to presented options
                else:
                    print('\nInvalid selection, please try again.')

            # User requested to skip file...
            if skip is True:
                cprint('  - Skipping rename, as per user request.', 'yellow')
                continue

            # User requested to exit...
            elif abort is True:
                cprint('  - Exiting, as per user request.', 'yellow')
                return

        # Attempt to process file
        cprint('\nProcessing File', attrs=['bold'])
        media = meta['media']
        destination = options[f'{media}_destination']
        action = 'moving' if destination else 'renaming'
        template = options[f'{media}_template']
        reformat = meta.format(template)
        new_path = f'{destination}/{reformat}' if destination else reformat
        try:
            if not directives['test_run'] is True:
                move(file, meta, **options)
        except IOError as e:
            cprint(f'  - Error {action}!', 'red')
            if options['verbose']:
                print(e)
            continue
        else:
            print(f"  - {action} to '{new_path}'")

        cprint('  - Success!', 'green')
        success_count += 1

    # Summarize session outcome
    if not detection_count:
        cprint('\nNo media files found. "mnamer --help" for usage.', 'yellow')
        return

    if success_count == 0:
        outcome_colour = 'red'
    elif success_count < detection_count:
        outcome_colour = 'yellow'
    else:
        outcome_colour = 'green'
    cprint(
        f'\nSuccessfully processed {success_count}'
        f' out of {detection_count} files',
        outcome_colour
    )


if __name__ == '__main__':
    main()
