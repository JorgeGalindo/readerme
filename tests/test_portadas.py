import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
import httpx

import portadas
import server


# Minimal versions of the opening-story markup observed on the public sites.
# Synthetic titles keep the fixtures independent of today's news.
OPENINGS = {
    "elpais": '<article class="c c-d"><header><h2 class="c_t"><a href="/noticia">{title}</a></h2></header></article>',
    "elmundo": '<h2 class="ue-c-live-feed__item-headline"><a href="/directo">Última hora del directo</a></h2><article><a href="/juegos/crucigrama/"><h2 class="ue-c-cover-content__headline">Completa el tablero</h2></a></article><article><a href="/espana/2026/11/07/noticia"><h2 class="ue-c-cover-content__headline">{title}</h2></a></article>',
    "elconfidencial": '<a class="tickerWidget__link" href="/ticker">Noticia del ticker</a><article class="teaser"><a class="teaser__titleLink" href="/noticia"><div class="h1">{title}</div></a></article>',
    "theobjective": '<article><h2 class="tno-blocks-article-top__title"><a href="/noticia">{title}</a></h2></article>',
    "abc": '<article><div><h2 class="v-a-t"><a href="/noticia">{title}</a></h2></div></article>',
    "eldiario": '<article><div><h2 class="ni-title bold"><a href="/noticia">{title}</a></h2></div></article>',
    "larazon": '<article><header><h2 class="article__title"><a href="/noticia">{title}</a></h2></header></article>',
    "lavanguardia": '<article class="article-module"><div><h2 class="title"><a href="/noticia">{title}</a></h2></div></article>',
    "ara": '<h3><a href="/tema">Tema del día</a></h3><div class="combo-title--article"><a class="combo-title-wrapper" href="/noticia"><h2>{title}</h2></a></div>',
    "elespanol": '<article class="art"><div><h2 class="art__title"><a href="/noticia">{title}</a></h2></div></article>',
    "publico": '<article><div><h2 class="title font-serif"><a href="/noticia">{title}</a></h2></div></article>',
    "20minutos": '<article><h2 class="c-article__title"><a href="/noticia">{title}</a></h2></article>',
    "infolibre": '<div class="t-news"><h1 class="ni-title"><a href="/noticia">{title}</a></h1></div>',
    "vozpopuli": '<article><div class="block-post-title"><h2><a href="/noticia">{title}</a></h2></div></article>',
}


class ExtractionTests(unittest.TestCase):
    def test_all_newspapers_select_the_opening_not_logos_tickers_or_later_stories(self):
        for paper in portadas.NEWSPAPERS:
            with self.subTest(paper=paper.id):
                opening = OPENINGS[paper.id]
                html = '<h1><a href="/">Logotipo</a></h1><h2><a href="/ultimas">Última hora</a></h2>'
                html += opening.format(title='Titular <em>principal</em> &amp; actualidad')
                html += opening.format(title='Noticia secundaria')
                title, url = portadas.extract_headline(html, paper)
                self.assertEqual(title, 'Titular principal & actualidad')
                self.assertTrue(url.startswith('https://'))
                self.assertTrue(url.endswith('/noticia'))

    def test_hidden_navigation_and_templates_do_not_supply_the_headline(self):
        paper = portadas.NEWSPAPERS[0]
        opening = OPENINGS[paper.id]
        hidden = opening.format(title='No es la apertura')
        html = f'<nav>{hidden}</nav><template>{hidden}</template><section hidden>{hidden}</section>'
        html += f'<section aria-hidden="true">{hidden}</section>'
        html += opening.format(title='La apertura visible')
        self.assertEqual(portadas.extract_headline(html, paper)[0], 'La apertura visible')

    def test_no_headline_does_not_fall_back_to_an_unrelated_heading(self):
        for paper in portadas.NEWSPAPERS:
            with self.subTest(paper=paper.id):
                self.assertIsNone(portadas.extract_headline('<h2><a href="/otra">Una noticia cualquiera</a></h2>', paper))

    def test_relative_links_and_unsafe_links(self):
        paper = portadas.NEWSPAPERS[0]
        opening = OPENINGS[paper.id].format(title='Titular')
        for bad in ('javascript:alert(1)', 'data:text/html,test', '#', '/'):
            with self.subTest(url=bad):
                self.assertIsNone(portadas.extract_headline(opening.replace('/noticia', bad), paper))
        self.assertEqual(portadas.extract_headline(opening, paper)[1], 'https://elpais.com/noticia')


class ElMundoTests(unittest.TestCase):
    def test_games_carousel_above_the_opening_is_skipped(self):
        paper = portadas.BY_ID['elmundo']
        html = OPENINGS['elmundo'].format(title='La apertura')
        self.assertEqual(portadas.extract_headline(html, paper),
                         ('La apertura', 'https://www.elmundo.es/espana/2026/11/07/noticia'))


class FetchTests(unittest.TestCase):
    def mock_client(self, respond):
        return patch.object(portadas.httpx, 'Client',
                            return_value=httpx.Client(transport=httpx.MockTransport(respond)))

    def test_one_newspaper_is_fetched_with_its_time(self):
        def respond(request):
            self.assertEqual(str(request.url), 'https://www.abc.es/')
            return httpx.Response(200, text=OPENINGS['abc'].format(title='Titular de ABC'))
        with self.mock_client(respond):
            row = portadas.fetch_one('abc')
        self.assertEqual(row['title'], 'Titular de ABC')
        self.assertEqual(row['url'], 'https://www.abc.es/noticia')
        self.assertIn('updated_at', row)

    def test_slow_or_failing_newspaper_returns_an_empty_row(self):
        for failure in (httpx.ReadTimeout('slow newspaper'), httpx.Response(503)):
            with self.subTest(failure=type(failure).__name__):
                def respond(request, failure=failure):
                    if isinstance(failure, Exception):
                        raise failure
                    return failure
                with self.mock_client(respond):
                    row = portadas.fetch_one('elpais')
                self.assertEqual((row['id'], row['title'], row['url']), ('elpais', None, None))

    def test_unknown_newspaper(self):
        self.assertIsNone(portadas.fetch_one('noexiste'))


class FrontPageTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_first_tab_is_portadas_and_rendering_it_does_not_fetch_news(self):
        with patch.object(portadas, 'fetch_one') as fetch:
            response = self.client.get('/')
            self.assertEqual(response.status_code, 200)
            soup = BeautifulSoup(response.data, 'html.parser')
            tabs = soup.select('.page-nav a')
            self.assertEqual(tabs[0].get_text(), 'Portadas')
            self.assertEqual(tabs[0]['aria-current'], 'page')
            self.assertEqual(tabs[1]['href'], '/main')
            self.assertEqual(len(soup.select('[data-source]')), len(portadas.NEWSPAPERS))
            self.assertEqual(soup.select_one('#refreshPortadas').get_text(), 'Actualizar')
            self.assertNotIn('/static/read.js', response.get_data(as_text=True))
            fetch.assert_not_called()

    def test_each_newspaper_has_its_own_uncached_endpoint(self):
        with patch.object(portadas, 'fetch_one', side_effect=[
            {'id': 'elpais', 'title': 'Primero', 'url': 'https://elpais.com/a'},
            {'id': 'elpais', 'title': 'Segundo', 'url': 'https://elpais.com/b'},
        ]) as fetch:
            first = self.client.get('/api/portadas/elpais')
            second = self.client.get('/api/portadas/elpais')
            self.assertEqual(first.json['title'], 'Primero')
            self.assertEqual(second.json['title'], 'Segundo')
            self.assertEqual(second.headers['Cache-Control'], 'no-store')
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(self.client.get('/api/portadas/noexiste').status_code, 404)

    def test_existing_pages_keep_main_and_add_portadas_first(self):
        with patch.object(server.storage, 'read_json', return_value={}), \
             patch.object(server.storage, 'exists', return_value=False), \
             patch.object(server.read_store, 'load', return_value={}):
            for path in ('/main', '/espana', '/thinktanks', '/papers'):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    tabs = BeautifulSoup(response.data, 'html.parser').select('.page-nav a')
                    self.assertEqual(tabs[0]['href'], '/')
                    self.assertEqual(tabs[0].get_text(), 'Portadas')
                    self.assertEqual(tabs[1]['href'], '/main')


if __name__ == '__main__':
    unittest.main()
