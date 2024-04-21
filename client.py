import sys
import atexit
import libtorrent as lt
import time
import os.path
from prettytable import PrettyTable


class WindowsConsole:
    def __init__(self):
        self.console = Console.getconsole()

    def clear(self):
        self.console.page()

    def write(self, str):
        self.console.write(str)

    def sleep_and_input(self, seconds):
        time.sleep(seconds)
        if msvcrt.kbhit():
            return msvcrt.getch()
        return None


class UnixConsole:
    def __init__(self):
        self.fd = sys.stdin
        self.old = termios.tcgetattr(self.fd.fileno())
        new = termios.tcgetattr(self.fd.fileno())
        new[3] = new[3] & ~termios.ICANON
        new[6][termios.VTIME] = 0
        new[6][termios.VMIN] = 1
        termios.tcsetattr(self.fd.fileno(), termios.TCSADRAIN, new)

        atexit.register(self._onexit)

    def _onexit(self):
        termios.tcsetattr(self.fd.fileno(), termios.TCSADRAIN, self.old)

    def clear(self):
        sys.stdout.write('\033[2J\033[0;0H')
        sys.stdout.flush()

    def write(self, str):
        sys.stdout.write(str)
        sys.stdout.flush()

    def sleep_and_input(self, seconds):
        read, __, __ = select.select(
            [self.fd.fileno()], [], [], seconds)
        if len(read) > 0:
            return self.fd.read(1)
        return None


if os.name == 'nt':
    import Console
    import msvcrt
else:
    import termios
    import select


def write_line(console, line):
    console.write(line)


def add_suffix(val):
    prefix = ['B', 'kB', 'MB', 'GB', 'TB']
    for i in range(len(prefix)):
        if abs(val) < 1000:
            if i == 0:
                return '%5.3g%s' % (val, prefix[i])
            else:
                return '%4.3g%s' % (val, prefix[i])
        val /= 1000

    return '%6.3gPB' % val


def progress_bar(progress, width):
    assert(progress <= 1)
    progress_chars = int(progress * width + 0.5)
    return progress_chars * '#' + (width - progress_chars) * '-'


def print_peer_info(console, peers):
    table = PrettyTable(['Download', 'Upload', 'Progress', 'Client'])

    for p in peers:
        if p.flags & lt.peer_info.connecting:
            continue
        elif p.flags & lt.peer_info.handshake:
            continue

        down_speed = '%s/s' % (add_suffix(p.down_speed))
        up_speed = '%s/s' % (add_suffix(p.up_speed))

        progress = ''
        if p.downloading_piece_index >= 0:
            assert(p.downloading_progress <= p.downloading_total)
            progress = progress_bar(float(p.downloading_progress) / p.downloading_total, 15)
        else:
            progress = progress_bar(0, 15)

        if p.flags & lt.peer_info.handshake:
            client = 'waiting for handshake'
        elif p.flags & lt.peer_info.connecting:
            client = 'connecting to peer'
        else:
            client = p.client[:10]

        table.add_row([down_speed, up_speed, progress, client])

    write_line(console, table.get_string() + '\n')
    # print(table.get_string() + "\n")

def print_download_queue(console, download_queue):

    out = ""

    for e in download_queue:
        out += '%4d: [' % e['piece_index']
        for b in e['blocks']:
            s = b['state']
            if s == 3:
                out += '#'
            elif s == 2:
                out += '='
            elif s == 1:
                out += '-'
            else:
                out += ' '
        out += ']\n'

    write_line(console, out)


def add_torrent(ses, filename, options):
    atp = lt.add_torrent_params()
    if filename.startswith('magnet:'):
        atp = lt.parse_magnet_uri(filename)
    else:
        ti = lt.torrent_info(filename)
        resume_file = os.path.join(options.save_path, ti.name() + '.fastresume')
        try:
            atp = lt.read_resume_data(open(resume_file, 'rb').read())
        except Exception as e:
            print('failed to open resume file "%s": %s' % (resume_file, e))
        atp.ti = ti

    atp.save_path = options.save_path
    atp.storage_mode = lt.storage_mode_t.storage_mode_sparse
    atp.flags |= lt.torrent_flags.duplicate_is_error \
        | lt.torrent_flags.auto_managed \
        | lt.torrent_flags.duplicate_is_error
    ses.async_add_torrent(atp)


def print_directory_tree(directory, indent=''):
    items = sorted(os.listdir(directory))  # Sort items alphabetically
    for item in items:
        item_path = os.path.join(directory, item)
        if os.path.isdir(item_path):
            print(indent + '|-- ' + item)
            print_directory_tree(item_path, indent + '    ')
        else:
            print(indent + '|-- ' + item)


def convert_byte(byte):
    if byte < 0:
        return "Số byte không hợp lệ"

    elif byte < 1024:
        return f"{byte} B"

    elif byte < 1024 ** 2:
        return f"{byte / 1024:.2f} kB"

    elif byte < 1024 ** 3:
        return f"{byte / (1024 ** 2):.2f} MB"

    else:
        return f"{byte / (1024 ** 3):.2f} GB"


def main():
    from optparse import OptionParser

    parser = OptionParser()

    parser.add_option('-p', '--port', type='int', help='set listening port')

    parser.add_option(
        '-i', '--listen-interface', type='string',
        help='set interface for incoming connections', )

    parser.add_option(
        '-o', '--outgoing-interface', type='string',
        help='set interface for outgoing connections')

    parser.add_option(
        '-d', '--max-download-rate', type='float',
        help='the maximum download rate given in kB/s. 0 means infinite.')

    parser.add_option(
        '-u', '--max-upload-rate', type='float',
        help='the maximum upload rate given in kB/s. 0 means infinite.')

    parser.add_option(
        '-s', '--save-path', type='string',
        help='the path where the downloaded file/folder should be placed.')

    parser.add_option(
        '-r', '--proxy-host', type='string',
        help='sets HTTP proxy host and port (separated by \':\')')

    parser.set_defaults(
        port=6881,
        listen_interface='0.0.0.0',
        outgoing_interface='',
        max_download_rate=0,
        max_upload_rate=0,
        save_path='./output/',
        proxy_host=''
    )

    (options, args) = parser.parse_args()

    if options.port < 0 or options.port > 65525:
        options.port = 6881

    options.max_upload_rate *= 1000
    options.max_download_rate *= 1000

    if options.max_upload_rate <= 0:
        options.max_upload_rate = -1
    if options.max_download_rate <= 0:
        options.max_download_rate = -1

    settings = {
        'user_agent': 'python_client/' + lt.__version__,
        'listen_interfaces': '%s:%d' % (options.listen_interface, options.port),
        'download_rate_limit': int(options.max_download_rate),
        'upload_rate_limit': int(options.max_upload_rate),
        'alert_mask': lt.alert.category_t.all_categories,
        'outgoing_interfaces': options.outgoing_interface,
    }

    if options.proxy_host != '':
        settings['proxy_hostname'] = options.proxy_host.split(':')[0]
        settings['proxy_type'] = lt.proxy_type_t.http
        settings['proxy_port'] = options.proxy_host.split(':')[1]

    ses = lt.session(settings)

    # map torrent_handle to torrent_status
    torrents = {}
    alerts_log = []

    os.system('clear')
    print('\nFiles in input folder:\n')
    print_directory_tree('./input')

    torrent_file = "input/" + input("\nEnter your torrent file you want to download: {fileName}.torrent = ") + ".torrent"

    add_torrent(ses, torrent_file, options)

    start_time = time.time()

    for f in args:
        add_torrent(ses, f, options)

    if os.name == 'nt':
        console = WindowsConsole()
    else:
        console = UnixConsole()

    flag = False

    alive = True
    while alive:
        os.system('clear')

        # Lấy số lượng pieces đã tải về
        h = ses.add_torrent({'ti': lt.torrent_info(torrent_file), 'save_path': './output/'})
        num_pieces_downloaded = h.status().num_pieces

        if lt.torrent_info(torrent_file).num_pieces() == num_pieces_downloaded:
            print('Files downloaded successfully.')
            flag = True
            break


        out = ''

         # Calculate elapsed time
        elapsed_time = time.time() - start_time
        hours, remainder = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        elapsed_time_str = "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))

        text = "elapsed time: " + elapsed_time_str
        write_line(console, text)

        for h, t in torrents.items():
            out += '\ntorrent name: %-40s\n' % t.name[:40]
            out += '\n'
            if t.state != lt.torrent_status.seeding:
                state_str = ['queued', 'checking', 'downloading metadata',
                             'downloading', 'finished', 'seeding',
                             '', 'checking fastresume']
                out += state_str[t.state] + ' '

                out += '|' + progress_bar(t.progress, 49) + '|'
                out += '  %5.4f%% ' % (t.progress * 100)
                out += '\n'

                out += 'total downloaded: '
                out += convert_byte(t.total_done)
                out += '\n'

                out += '\npeers: %d \tseeds: %d' % \
                    (t.num_peers, t.num_seeds)
                out += "\t\tpieces: " + str(num_pieces_downloaded)  + ' / ' + str(lt.torrent_info(torrent_file).num_pieces())+ '\n'
                out += '\n'

            out += 'download: %s/s (%s) ' \
                % (add_suffix(t.download_rate), add_suffix(t.total_download))
            out += '\t\tupload: %s/s (%s) ' \
                % (add_suffix(t.upload_rate), add_suffix(t.total_upload))

            if t.state != lt.torrent_status.seeding:
                out += '\n\ninfo-hash: %s\n' % lt.torrent_info(torrent_file).info_hash()
                out += 'next announce: %s\n' % t.next_announce
                out += '\ntracker: %s\n' % t.current_tracker

            write_line(console, out)

            print_peer_info(console, t.handle.get_peer_info())

            if t.state != lt.torrent_status.seeding:
                try:
                    out = '\n'
                    fp = h.file_progress()
                    ti = t.torrent_file
                    for idx, p in enumerate(fp):
                        out += progress_bar(p / float(ti.files().file_size(idx)), 20)
                        out += ' ' + ti.files().file_path(idx) + '\n'
                    write_line(console, out)
                except Exception:
                    pass
            write_line(console, '\n')
            print_download_queue(console, t.handle.get_download_queue())

        write_line(console, 76 * '-' + '\n')
        write_line(console, 'Press (q) to quit...\n')
        write_line(console, 76 * '-' + '\n')

        alerts = ses.pop_alerts()
        for a in alerts:
            alerts_log.append(a.message())

            # add new torrents to our list of torrent_status
            if isinstance(a, lt.add_torrent_alert):
                h = a.handle
                h.set_max_connections(60)
                h.set_max_uploads(-1)
                torrents[h] = h.status()

            # update our torrent_status array for torrents that have
            # changed some of their state
            if isinstance(a, lt.state_update_alert):
                for s in a.status:
                    torrents[s.handle] = s

        if len(alerts_log) > 20:
            alerts_log = alerts_log[-20:]

        # for a in alerts_log:
        #     write_line(console, a + '\n')

        c = console.sleep_and_input(0.5)

        ses.post_torrent_updates()
        if not c:
            continue

        if c == 'r':
            for h in torrents:
                h.force_reannounce()
        elif c == 'q':
            alive = False
        elif c == 'p':
            for h in torrents:
                h.pause()
        elif c == 'u':
            for h in torrents:
                h.resume()

    ses.pause()
    for h, t in torrents.items():
        if not h.is_valid() or not t.has_metadata:
            continue
        h.save_resume_data()

    while len(torrents) > 0:
        if flag == False:
            alerts = ses.pop_alerts()
            for a in alerts:
                if isinstance(a, lt.save_resume_data_alert):
                    print(a)
                    data = lt.write_resume_data_buf(a.params)
                    h = a.handle
                    if h in torrents:
                        open(os.path.join(options.save_path, torrents[h].name + '.fastresume'), 'wb').write(data)
                        del torrents[h]

                if isinstance(a, lt.save_resume_data_failed_alert):
                    h = a.handle
                    if h in torrents:
                        print('failed to save resume data for ', torrents[h].name)
                        del torrents[h]
            time.sleep(0.5)


main()
