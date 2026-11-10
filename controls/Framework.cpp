/*
Framework.cpp -- base menu fullscreen root window
Copyright (C) 2017 a1batross

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
*/
#include "Framework.h"
#include "PicButton.h"
#include "Utils.h"      // L()
#include <string.h>

// ------------------------------------------------------------ banner titles
// Page banners are now rendered as TEXT with UI_DrawString instead of blitting
// a gfx/shell/head_*.bmp. Every menu still passes the same ART_BANNER path to
// SetPicture(), so we map the stem to a localization key here and leave the
// 25+ call sites untouched. Keys live in mainui_schinese.txt; in a language
// with no entry L() returns the key itself and we fall back to the English
// caption, so English builds stay readable.
struct banner_title_t
{
	const char *stem;
	const char *key;
	const char *english;
};

static const banner_title_t s_BannerTitles[] =
{
	{ "head_config", "BANNER_CONFIG", "OPTIONS" },
	{ "head_audio", "BANNER_AUDIO", "AUDIO" },
	{ "head_video", "BANNER_VIDEO", "VIDEO" },
	{ "head_vidmodes", "BANNER_VIDMODES", "VIDEO MODES" },
	{ "head_vidoptions", "BANNER_VIDOPTIONS", "VIDEO OPTIONS" },
	{ "head_controls", "BANNER_CONTROLS", "CONTROLS" },
	{ "head_advanced", "BANNER_ADVANCED", "ADVANCED" },
	{ "head_advoptions", "BANNER_ADVOPTIONS", "ADV OPTIONS" },
	{ "head_gamepad", "BANNER_GAMEPAD", "GAMEPAD" },
	{ "head_gyro", "BANNER_GYRO", "GYRO" },
	{ "head_keyboard", "BANNER_KEYBOARD", "KEYBOARD" },
	{ "head_newgame", "BANNER_NEWGAME", "NEW GAME" },
	{ "head_single", "BANNER_SINGLE", "SINGLE PLAYER" },
	{ "head_multi", "BANNER_MULTI", "MULTIPLAYER" },
	{ "head_creategame", "BANNER_CREATEGAME", "CREATE GAME" },
	{ "head_custom", "BANNER_CUSTOM", "CUSTOM GAME" },
	{ "head_customize", "BANNER_CUSTOMIZE", "CUSTOMIZE" },
	{ "head_gameopts", "BANNER_GAMEOPTS", "GAME OPTIONS" },
	{ "head_load", "BANNER_LOAD", "LOAD GAME" },
	{ "head_save", "BANNER_SAVE", "SAVE GAME" },
	{ "head_saveload", "BANNER_SAVELOAD", "SAVE/LOAD" },
	{ "head_inetgames", "BANNER_INETGAMES", "INTERNET" },
	{ "head_lan", "BANNER_LAN", "LAN GAMES" },
	{ "head_filter", "BANNER_FILTER", "SERVER FILTER" },
	{ "head_specgames", "BANNER_SPECGAMES", "SPECTATE" },
	{ "head_gore", "BANNER_GORE", "GORE" },
	{ "head_readme", "BANNER_README", "READ ME" },
	{ "head_touch", "BANNER_TOUCH", "TOUCH" },
	{ "head_touch_buttons", "BANNER_TOUCH_BUTTONS", "TOUCH BUTTONS" },
	{ "head_touchoptions", "BANNER_TOUCHOPTIONS", "TOUCH OPTIONS" },
	{ "head_touch_options", "BANNER_TOUCH_OPTIONS", "TOUCH OPT" },
	{ "head_play", "BANNER_PLAY", "PLAY" },
	{ "head_record", "BANNER_RECORD", "RECORD" },
	{ "head_playrec", "BANNER_PLAYREC", "PLAY RECORD" },
	{ "head_room", "BANNER_ROOM", "ROOM" },
	{ "head_rooms", "BANNER_ROOMS", "ROOMS" },
	{ "head_createroom", "BANNER_CREATEROOM", "CREATE ROOM" },
};

static const char *BannerTitle( const char *key, const char *english )
{
	const char *s = L( key );
	return ( s && *s && strcmp( s, key )) ? s : english;
}

// menu banners used fiexed rectangle (virtual screenspace at 640x480)
#define UI_BANNER_POSX		72
#define UI_BANNER_POSY		72
#define UI_BANNER_WIDTH		736
#define UI_BANNER_HEIGHT		128

CMenuFramework::CMenuFramework( const char *name ) : BaseClass( name )
{
	memset( m_apBtns, 0, sizeof( m_apBtns ) );
	m_iBtnsNum = 0;
	bannerAnimDirection = ANIM_NO;
}

CMenuFramework::~CMenuFramework()
{
	for( int i = 0; i < m_iBtnsNum; i++ )
	{
		RemoveItem( *( m_apBtns[i] ) );
		delete m_apBtns[i];
		m_apBtns[i] = NULL;
	}
}

void CMenuFramework::Show()
{
	BaseClass::Show();
}

void CMenuFramework::Draw()
{
	static int statusFadeTime;
	static CMenuBaseItem *lastItem;
	CMenuBaseItem *item;

	BaseClass::Draw();

	item = ItemAtCursor();
	// a1ba: maybe this should be somewhere else?
	if( item != lastItem )
	{
		if( item ) item->m_iLastFocusTime = uiStatic.realTime;
		statusFadeTime = uiStatic.realTime;

		lastItem = item;
	}

	// draw status text if status text isn't rendered at right side of an item
	// ideally, framework shouldn't even know about this but since everything
	// WON-styled goes here, let's leave it here...
	if( item && item == lastItem && !FBitSet( item->iFlags, QMF_NOTIFY ) && item->szStatusText != NULL )
	{
		float alpha = bound( 0, ((( uiStatic.realTime - statusFadeTime ) - 100 ) * 0.01f ), 1 );
		int r, g, b, x, len;

		EngFuncs::ConsoleStringLen( item->szStatusText, &len, NULL );

		UnpackRGB( r, g, b, uiColorHelp );
		EngFuncs::DrawSetTextColor( r, g, b, alpha * 255 );
		x = ( ScreenWidth - len ) * 0.5f; // centering

		EngFuncs::DrawConsoleString( x, uiStatic.yOffset + 720 * uiStatic.scaleY, item->szStatusText );
	}
	else statusFadeTime = uiStatic.realTime;
}

void CMenuFramework::Hide()
{
	BaseClass::Hide();
}

void CMenuFramework::Init()
{
	BaseClass::Init();
	pos.x = uiStatic.xOffset;
	pos.y = uiStatic.yOffset;
	size.w = uiStatic.width;
	size.h = 768;
}

void CMenuFramework::VidInit()
{
	pos.x = uiStatic.xOffset;
	pos.y = uiStatic.yOffset;
	size.w = uiStatic.width;
	size.h = 768;
	BaseClass::VidInit();
}

CMenuPicButton * CMenuFramework::AddButton(const char *szName, const char *szStatus, EDefaultBtns buttonPicId, CEventCallback onReleased, int iFlags)
{
	if( m_iBtnsNum >= MAX_FRAMEWORK_PICBUTTONS )
	{
		Host_Error( "Too many pic buttons in framework!" );
		return NULL;
	}

	CMenuPicButton *btn = new CMenuPicButton();

	btn->SetNameAndStatus( szName, szStatus );
	btn->SetPicture( buttonPicId );
	btn->iFlags |= iFlags;
	btn->onReleased = onReleased;
	btn->SetCoord( 72, 230 + m_iBtnsNum * 50 );
	AddItem( btn );

	m_apBtns[m_iBtnsNum++] = btn;

	return btn;
}

CMenuPicButton * CMenuFramework::AddButton( const char *szName, const char *szStatus, const char *szButtonPath, CEventCallback onReleased, int iFlags, int hotkey )
{
	if( m_iBtnsNum >= MAX_FRAMEWORK_PICBUTTONS )
	{
		Host_Error( "Too many pic buttons in framework!" );
		return NULL;
	}

	CMenuPicButton *btn = new CMenuPicButton();

	btn->SetNameAndStatus( szName, szStatus );
	btn->SetPicture( szButtonPath, hotkey );
	btn->iFlags |= iFlags;
	btn->onReleased = onReleased;
	btn->SetCoord( 72, 230 + m_iBtnsNum * 50 );
	AddItem( btn );

	m_apBtns[m_iBtnsNum++] = btn;

	return btn;
}

void CMenuFramework::RealignButtons( void )
{
	for( int i = 0, j = 0; i < m_iBtnsNum; i++ )
	{
		if( !m_apBtns[i]->IsVisible())
			continue;

		m_apBtns[i]->SetCoord( 72, 230 + j * 50 );
		m_apBtns[i]->CalcPosition();
		j++;
	}
}

bool CMenuFramework::KeyDown( int key )
{
	bool b = BaseClass::KeyDown( key );

	if( UI::Key::IsEscape( key ))
	{
		const CMenuBaseWindow *newWindow = WindowStack()->Current();

		if( newWindow != nullptr && newWindow != this && newWindow->IsRoot() )
		{
			PrepareBannerAnimation( ANIM_CLOSING, nullptr );
		}
	}

	return b;
}

void CMenuFramework::PrepareBannerAnimation( EAnimation direction, CMenuPicButton *initiator )
{
	// banner is not present, ignore
	if( banner.Parent() != this )
		return;

	bannerAnimDirection = direction;
	if( initiator )
	{
		bannerRects[0].pt = initiator->GetRenderPosition();
		bannerRects[0].sz = initiator->GetRenderSize();

		bannerRects[1].pt = banner.GetRenderPosition();
		bannerRects[1].sz = banner.GetRenderSize();

		banner.szName = initiator->szName;
	}
}

bool CMenuFramework::DrawAnimation()
{
	bool b = CMenuBaseWindow::DrawAnimation( );

	if( bannerAnimDirection != ANIM_NO )
	{
		float frac;

		if( bannerAnimDirection == ANIM_OPENING )
			frac = ( uiStatic.realTime - m_iTransitionStartTime ) / TTT_PERIOD;
		else
			frac = 1.0f - ( uiStatic.realTime - m_iTransitionStartTime ) / TTT_PERIOD;
		Rect r = Rect::Lerp( bannerRects[0], bannerRects[1], frac );

		banner.Draw( r.pt, r.sz );
	}

	if( b )
		bannerAnimDirection = ANIM_NO;

	return b;
}

CMenuFramework::CMenuBannerBitmap::CMenuBannerBitmap()
{
	SetRect( UI_BANNER_POSX, UI_BANNER_POSY, UI_BANNER_WIDTH, UI_BANNER_HEIGHT );
	szTitle = NULL;
}

void CMenuFramework::CMenuBannerBitmap::SetPicture(const char *pic)
{
	szTitle = NULL;

	if( pic )
	{
		const char *slash = strrchr( pic, '/' );
		const char *stem = slash ? slash + 1 : pic;

		for( size_t i = 0; i < sizeof( s_BannerTitles ) / sizeof( s_BannerTitles[0] ); i++ )
		{
			if( !stricmp( stem, s_BannerTitles[i].stem ))
			{
				szTitle = BannerTitle( s_BannerTitles[i].key, s_BannerTitles[i].english );
				break;
			}
		}
	}

	// Intentionally NOT image.Load( pic ): the caption is drawn with the
	// system font below. The old head_*.bmp files stay on disk as a fallback.
}

void CMenuFramework::CMenuBannerBitmap::Draw( Point pt, Size sz )
{
	// szTitle is deliberately independent of szName: PrepareBannerAnimation()
	// overwrites szName with the initiator button's caption during transitions.
	const char *text = szTitle ? szTitle : szName;
	if( !text || !*text )
		return;

	HFont font = uiStatic.hBannerFont ? uiStatic.hBannerFont : uiStatic.hBigFont;
	const int charH = Q_max( 12, sz.h * 2 / 3 );
	const uint flags = ETF_FORCECOL | ETF_NOSIZELIMIT;
	const uint justify = QM_CENTER;

	// Hard 1px outline: eight offset passes in black. Unlike the old additive
	// BMP path, ordinary blending gives us a genuine DARK rim here.
	static const int ox[8] = { -1, 1, 0, 0, -1, -1, 1, 1 };
	static const int oy[8] = {  0, 0,-1, 1, -1,  1,-1, 1 };
	for( int i = 0; i < 8; i++ )
	{
		Point p = pt;
		p.x += ox[i];
		p.y += oy[i];
		UI_DrawString( font, p, sz, text, uiColorBlack, charH, justify, flags );
	}

	// Glyph + real drop shadow (ETF_SHADOW draws a black offset copy).
	UI_DrawString( font, pt, sz, text, uiPromptTextColor, charH,
		justify, flags | ETF_SHADOW );
}

void CMenuFramework::CMenuBannerBitmap::Draw()
{
	CMenuFramework *pParent = (CMenuFramework *)Parent();

	if (pParent && (pParent->bannerAnimDirection == ANIM_OPENING || pParent->eTransitionType == ANIM_OPENING))
		return;

	Draw( m_scPos, m_scSize );
}

