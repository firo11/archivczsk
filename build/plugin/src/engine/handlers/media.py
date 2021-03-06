import traceback
from twisted.internet import defer

from Components.config import config
from Screens.MessageBox import MessageBox
from Screens.ChoiceBox import ChoiceBox

from item import ItemHandler
from folder import FolderItemHandler
from Plugins.Extensions.archivCZSK import _, log
from Plugins.Extensions.archivCZSK.gui.exception import AddonExceptionHandler, DownloadExceptionHandler, PlayExceptionHandler
from Plugins.Extensions.archivCZSK.engine.items import PExit, PVideo, PVideoResolved, PVideoNotResolved, PPlaylist
from Plugins.Extensions.archivCZSK.engine.tools.util import toString
from enigma import eTimer
from Plugins.Extensions.archivCZSK.compat import eConnectCallback


class MediaItemHandler(ItemHandler):
    """ Template class - handles Media Item interaction """

    def __init__(self, session, content_screen, content_provider, info_modes):
        ItemHandler.__init__(self, session, content_screen, info_modes)
        self.content_provider = content_provider

    def _open_item(self, item, mode='play', *args, **kwargs):
        self.play_item(item, mode, args, kwargs)

    
    # action:
        #   - play
        #   - watching /every 10minutes/
        #   - end
    def cmdStats(self, item, action, successCB=None, failCB=None):
        def open_item_success_cb(result):
            log.logDebug("Stats (%s) call success."%action)
            if paused:
                self.content_provider.pause()
            if successCB is not None:
                successCB()
        def open_item_error_cb(failure):
            log.logDebug("Stats (%s) call failed.\n%s"%(action,failure))
            if paused:
                self.content_provider.pause()
            if failCB is not None:
                failCB()

        paused = self.content_provider.isPaused()
        try:
            if paused:
                self.content_provider.resume()
            
            ppp = { 'cp': 'czsklib', 'stats':action, 'item': item.dataItem }
            # content provider must be in running state (not paused)
            self.content_provider.get_content(self.session, params=ppp, successCB=open_item_success_cb, errorCB=open_item_error_cb)
        except:
            log.logError("Stats call failed.\n%s"%traceback.format_exc())
            if paused:
                self.content_provider.pause()
            if failCB is not None:
                failCB()
            

    def play_item(self, item, mode='play', *args, **kwargs):
        def startWatchingTimer():
            self.cmdTimer.start(timerPeriod)
        def timerEvent():
            self.cmdStats(item, 'watching')
        def end_play():
            try:
                self.cmdTimer.stop()
                del self.cmdTimer
                del self.cmdTimer_conn
            except:
                log.logDebug("Release cmd timer failed.\n%s" % traceback.format_exc())
            self.content_screen.workingFinished()
            self.content_provider.resume()
            self.cmdStats(item, 'end')

        timerPeriod = 10*60*1000 #10min
        self.cmdTimer = eTimer()
        self.cmdTimer_conn = eConnectCallback(self.cmdTimer.timeout, timerEvent)

        self.content_screen.workingStarted()
        self.content_provider.pause()
        self.content_provider.play(self.session, item, mode, end_play)

        # send command
        self.cmdStats(item, 'play', successCB=startWatchingTimer)

    def download_item(self, item, mode="", *args, **kwargs):
        @DownloadExceptionHandler(self.session)
        def start_download(mode):
            try:
                self.content_provider.download(self.session, item, mode=mode)
            except Exception:
                self.content_screen.workingFinished()
                raise
        start_download(mode)

    def _init_menu(self, item):
        provider = self.content_provider
        if 'play' in provider.capabilities:
            item.add_context_menu_item(_("Play"),
                                                        action=self.play_item,
                                                        params={'item':item,
                                                        'mode':'play'})

        if 'play_and_download' in provider.capabilities:
            item.add_context_menu_item(_("Play and Download"),
                                       action=self.play_item,
                                       params={'item':item,
                                                      'mode':'play_and_download'})

        if 'download' in provider.capabilities:
            item.add_context_menu_item(_("Download"),
                                       action=self.download_item,
                                       params={'item':item,
                                                      'mode':'auto'})


class VideoResolvedItemHandler(MediaItemHandler):
    handles = (PVideoResolved, )
    def __init__(self, session, content_screen, content_provider):
        info_handlers = ['csfd','item']
        MediaItemHandler.__init__(self, session, content_screen, content_provider, info_handlers)



class VideoNotResolvedItemHandler(MediaItemHandler):
    handles = (PVideoNotResolved, )
    def __init__(self, session, content_screen, content_provider):
        info_modes = ['item','csfd']
        MediaItemHandler.__init__(self, session, content_screen, content_provider, ['item','csfd'])

    def _init_menu(self, item):
        MediaItemHandler._init_menu(self, item)
        item.add_context_menu_item(_("Resolve videos"),
                                       action=self._resolve_videos,
                                       params={'item':item})
        if 'favorites' in self.content_provider.capabilities:
            item.add_context_menu_item(_("Add Shortcut"), 
                    action=self.ask_add_shortcut, 
                    params={'item':item})
        else:
            item.remove_context_menu_item(_("Add Shortcut"), 
                    action=self.ask_add_shortcut, 
                    params={'item':item})

    def ask_add_shortcut(self, item):
        self.item = item
        self.session.openWithCallback(self.add_shortcut_cb, MessageBox,
                text="%s %s %s"%(_("Do you want to add"), toString(item.name),  _("shortcut?")),
                type=MessageBox.TYPE_YESNO)

    def add_shortcut_cb(self, cb):
        if cb:
            self.content_provider.create_shortcut(self.item)

    def play_item(self, item, mode='play', *args, **kwargs):

        def video_selected_callback(res_item):
            MediaItemHandler.play_item(self, res_item, mode)

        if config.plugins.archivCZSK.showVideoSourceSelection.value:
            self._resolve_video(item, video_selected_callback)
        else:
            self._resolve_videos(item)

    def download_item(self, item, mode="", *args, **kwargs):
        def wrapped(res_item):
            MediaItemHandler.download_item(self, res_item, mode)
            self.content_screen.workingFinished()
        self._resolve_video(item, wrapped)

    def _filter_by_quality(self, items):
        pass

    def _resolve_video(self, item, callback):

        def selected_source(answer):
            if answer is not None:
                # entry point of play video source
                callback(answer[1])
            else:
                self.content_screen.workingFinished()

        def open_item_success_cb(result):
            self.content_screen.stopLoading()
            self.content_screen.showList()
            list_items, __, __ = result
            self._filter_by_quality(list_items)
            if len(list_items) > 1:
                choices = []
                for i in list_items:
                    name = i.name
                    # TODO remove workaround of embedding
                    # quality in title in addons
                    if i.quality and i.quality not in i.name:
                        if "[???]" in i.name:
                            name = i.name.replace("[???]","[%s]"%(i.quality))
                        else:
                            name = "[%s] %s"%(i.quality, i.name)
                    choices.append((toString(name), i))
                self.session.openWithCallback(selected_source,
                        ChoiceBox, _("Please select source"),
                        list = choices,
                        skin_name = ["ArchivCZSKVideoSourceSelection"])
            elif len(list_items) == 1:
                item = list_items[0]
                callback(item)
            else: # no video
                self.content_screen.workingFinished()

        @AddonExceptionHandler(self.session)
        def open_item_error_cb(failure):
            self.content_screen.stopLoading()
            self.content_screen.showList()
            self.content_screen.workingFinished()
            failure.raiseException()
        self.content_screen.hideList()
        self.content_screen.startLoading()
        self.content_screen.workingStarted()
        self.content_provider.get_content(self.session, item.params, open_item_success_cb, open_item_error_cb)


    def _resolve_videos(self, item):
        def open_item_success_cb(result):
            list_items, screen_command, args = result
            list_items.insert(0, PExit())
            if screen_command is not None:
                self.content_screen.resolveCommand(screen_command, args)
            else:
                self.content_screen.save()
                content = {'parent_it':item, 'lst_items':list_items, 'refresh':False}
                self.content_screen.stopLoading()
                self.content_screen.load(content)
                self.content_screen.showList()
                self.content_screen.workingFinished()

        @AddonExceptionHandler(self.session)
        def open_item_error_cb(failure):
            self.content_screen.stopLoading()
            self.content_screen.showList()
            self.content_screen.workingFinished()
            failure.raiseException()

        self.content_screen.workingStarted()
        self.content_screen.hideList()
        self.content_screen.startLoading()
        self.content_provider.get_content(self.session, item.params, open_item_success_cb, open_item_error_cb)



class PlaylistItemHandler(MediaItemHandler):
    handles = (PPlaylist, )
    def __init__(self, session, content_screen, content_provider, info_modes=None):
        if not info_modes:
            info_modes = ['item','csfd']
        MediaItemHandler.__init__(self, session, content_screen, content_provider, info_modes)

    def show_playlist(self, item):
        self.content_screen.save()
        list_items = [PExit()]
        list_items.extend(item.playlist[:])
        content = {'parent_it':item,
                          'lst_items':list_items,
                          'refresh':False}
        self.content_screen.load(content)

    def _init_menu(self, item, *args, **kwargs):
        provider = self.content_provider
        if 'play' in provider.capabilities:
            item.add_context_menu_item(_("Play"),
                                                        action=self.play_item,
                                                        params={'item':item,
                                                        'mode':'play'})
        item.add_context_menu_item(_("Show playlist"),
                                   action=self.show_playlist,
                                   params={'item':item})
