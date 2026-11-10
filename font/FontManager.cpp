/*
FontManager.cpp - font manager
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
#include <locale.h>
#include "FontManager.h"
#include "BaseMenu.h"
#include "Utils.h"

#include "BaseFontBackend.h"

#if defined(MAINUI_USE_FREETYPE)
#include "FreeTypeFont.h"
#elif defined(MAINUI_USE_STB)
#include "StbFont.h"
#elif defined(_WIN32)
#include "WinAPIFont.h"
#endif

#include "BitmapFont.h"
#include "utflib.h"

#define DEFAULT_MENUFONT "SimSun"
#define DEFAULT_CONFONT  "SimSun"
#define DEFAULT_WEIGHT   500

// ---------------------------------------------------------------- font config
// Every menu face comes straight from the OS fonts folder. The JSON config is
// read through the VFS (config/fonts.json), but the font binary itself is read
// with stdio: VFS rejects absolute paths, and we deliberately do NOT ship a
// TTF/TTC inside the game tree. "@system:" marks such a path for the loader.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define FONT_CONFIG_PATH   "config/fonts.json"
#define FONT_SYSTEM_PREFIX "@system:"

struct font_config_t
{
	bool loaded;
	char directory[256];
	char file[128];
	char name[64];
	char fullpath[512];
	int  face;
};
static font_config_t s_FontConfig;

// Minimal JSON reader. This config is a flat object of "key": "value" and
// "key": number pairs; only four keys are needed, so pulling in a full JSON
// parser would be a needless dependency. Escapes \\, \", \n, \t, \r are
// handled (notably %WINDIR%\\Fonts in the "directory" value).
static bool FC_String( const char *buf, const char *key, char *out, size_t outlen )
{
	char token[64];
	snprintf( token, sizeof( token ), "\"%s\"", key );
	const char *p = strstr( buf, token );
	if( !p ) return false;
	p = strchr( p + strlen( token ), ':' );
	if( !p ) return false;
	p++;
	while( *p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' ) p++;
	if( *p != '"' ) return false;
	p++;

	size_t n = 0;
	while( *p && *p != '"' && n + 1 < outlen )
	{
		if( *p == '\\' && p[1] )
		{
			p++;
			switch( *p )
			{
			case 'n': out[n++] = '\n'; break;
			case 't': out[n++] = '\t'; break;
			case 'r': out[n++] = '\r'; break;
			default:  out[n++] = *p;  break;
			}
			p++;
		}
		else out[n++] = *p++;
	}
	out[n] = 0;
	return n > 0;
}

static bool FC_Int( const char *buf, const char *key, int *out )
{
	char token[64];
	snprintf( token, sizeof( token ), "\"%s\"", key );
	const char *p = strstr( buf, token );
	if( !p ) return false;
	p = strchr( p + strlen( token ), ':' );
	if( !p ) return false;
	p++;
	while( *p == ' ' || *p == '\t' ) p++;
	if( *p != '-' && !isdigit( (unsigned char)*p )) return false;
	*out = atoi( p );
	return true;
}

static void FC_ExpandEnv( const char *src, char *dst, size_t dstlen )
{
	if( src[0] == '%' )
	{
		const char *end = strchr( src + 1, '%' );
		if( end )
		{
			char name[64];
			size_t n = end - ( src + 1 );
			if( n < sizeof( name ))
			{
				memcpy( name, src + 1, n );
				name[n] = 0;
				const char *val = getenv( name );
				if( val )
				{
					snprintf( dst, dstlen, "%s%s", val, end + 1 );
					return;
				}
			}
		}
	}
	Q_strncpy( dst, src, dstlen );
}

static void FC_Load( void )
{
	if( s_FontConfig.loaded )
		return;
	s_FontConfig.loaded = true;   // try only once, even on failure

	// built-in defaults, used when config/fonts.json is absent
	Q_strncpy( s_FontConfig.directory, "%WINDIR%\\Fonts", sizeof( s_FontConfig.directory ));
	Q_strncpy( s_FontConfig.file, "simsun.ttc", sizeof( s_FontConfig.file ));
	Q_strncpy( s_FontConfig.name, "SimSun", sizeof( s_FontConfig.name ));
	s_FontConfig.face = 0;

	int len = 0;
	char *raw = (char *)EngFuncs::COM_LoadFile( FONT_CONFIG_PATH, &len );
	if( raw && len > 0 )
	{
		char *text = (char *)malloc( len + 1 );
		if( text )
		{
			memcpy( text, raw, len );
			text[len] = 0;
			FC_String( text, "directory", s_FontConfig.directory, sizeof( s_FontConfig.directory ));
			FC_String( text, "file", s_FontConfig.file, sizeof( s_FontConfig.file ));
			FC_String( text, "name", s_FontConfig.name, sizeof( s_FontConfig.name ));
			FC_Int( text, "face", &s_FontConfig.face );
			free( text );
		}
		EngFuncs::COM_FreeFile( raw );
	}
	else Con_Printf( "FontConfig: %s missing, using built-in defaults\n", FONT_CONFIG_PATH );

	char dir[256];
	FC_ExpandEnv( s_FontConfig.directory, dir, sizeof( dir ));
	snprintf( s_FontConfig.fullpath, sizeof( s_FontConfig.fullpath ), "%s/%s", dir, s_FontConfig.file );
	Con_Printf( "FontConfig: %s (face %d, %s)\n", s_FontConfig.fullpath, s_FontConfig.face, s_FontConfig.name );
}

int CFontManager::GetFontFaceIndex() const
{
	FC_Load();
	return s_FontConfig.face;
}

CFontManager *g_FontMgr;

CFontManager::CFontManager()
{
#ifdef MAINUI_USE_FREETYPE
	FT_Init_FreeType( &CFreeTypeFont::m_Library );
#endif
	m_Fonts.EnsureCapacity( 4 );
	m_FontFiles.EnsureCapacity( 2 );
	m_pSystemFontData = NULL;
	m_iSystemFontDataLen = 0;
}

CFontManager::~CFontManager()
{
	DeleteAllFonts();
#ifdef MAINUI_USE_FREETYPE
	FT_Done_FreeType( CFreeTypeFont::m_Library );
	CFreeTypeFont::m_Library = NULL;
#endif

	FOR_EACH_HASHMAP( m_FontFiles, i )
	{
		byte *p = m_FontFiles.Element( i ).data;
		EngFuncs::COM_FreeFile( p );
	}

	m_FontFiles.Purge();

	delete[] m_pSystemFontData;
	m_pSystemFontData = NULL;
	m_iSystemFontDataLen = 0;
}

void CFontManager::VidInit( void )
{
	static float prevScale = 0;

	float scale = uiStatic.scaleY;

	if( !prevScale
#ifndef SCALE_FONTS // complete disables font re-rendering
	|| fabs( scale - prevScale ) > 0.1f
#endif
	)
	{
		DeleteAllFonts();
		uiStatic.hDefaultFont = CFontBuilder( DEFAULT_MENUFONT, UI_MED_CHAR_HEIGHT * scale, DEFAULT_WEIGHT )
			.SetHandleNum( QM_DEFAULTFONT )
			.Create();
		uiStatic.hSmallFont   = CFontBuilder( DEFAULT_MENUFONT, UI_SMALL_CHAR_HEIGHT * scale, DEFAULT_WEIGHT )
			.SetHandleNum( QM_SMALLFONT )
			.Create();
		uiStatic.hBigFont     = CFontBuilder( DEFAULT_MENUFONT, UI_BIG_CHAR_HEIGHT * scale, DEFAULT_WEIGHT )
			.SetHandleNum( QM_BIGFONT )
			.Create();
		uiStatic.hBoldFont = CFontBuilder( DEFAULT_MENUFONT, UI_MED_CHAR_HEIGHT * scale, 1000 )
			.SetHandleNum( QM_BOLDFONT )
			.Create();

		// Large face for runtime-rendered page banners. Same system font as
		// everything else, just taller; CJK glyphs are rasterized on demand
		// by CBaseFont::EnsureDynamicGlyph(), no codepoint ranges needed.
		uiStatic.hBannerFont = CFontBuilder( DEFAULT_MENUFONT, (int)( UI_BIG_CHAR_HEIGHT * scale * 2 ), 1000 )
			.Create();

		if( !uiStatic.lowmemory )
		{
			uiStatic.hLightBlur = CFontBuilder( DEFAULT_MENUFONT, UI_MED_CHAR_HEIGHT * scale, DEFAULT_WEIGHT )
				.SetBlurParams( 2 * scale, 1.25f )
				.Create();

			uiStatic.hHeavyBlur = CFontBuilder( DEFAULT_MENUFONT, UI_MED_CHAR_HEIGHT * scale, DEFAULT_WEIGHT )
				.SetBlurParams( 8 * scale, 2.0f )
				.Create();
		}

		uiStatic.hConsoleFont = CFontBuilder( DEFAULT_CONFONT, UI_CONSOLE_CHAR_HEIGHT * scale, 500 )
			.SetOutlineSize()
			.Create();
		prevScale = scale;
	}
}

void CFontManager::DeleteAllFonts()
{
	for( int i = 0; i < m_Fonts.Count(); i++ )
	{
		delete m_Fonts[i];
	}
	m_Fonts.RemoveAll();
}

void CFontManager::DeleteFont(HFont hFont)
{
	CBaseFont *font = GetIFontFromHandle(hFont);
	if( font )
	{
		m_Fonts[hFont-1] = NULL;

		delete font;
	}
}

CBaseFont *CFontManager::GetIFontFromHandle(HFont font)
{
	if( m_Fonts.IsValidIndex( font - 1 ) )
		return m_Fonts[font-1];

	return NULL;
}

int CFontManager::GetEllipsisWide(HFont font)
{
	if( m_Fonts.IsValidIndex( font - 1 ) )
		return m_Fonts[font-1]->GetEllipsisWide();
	return 0;
}

void CFontManager::GetCharABCWide(HFont font, int ch, int &a, int &b, int &c)
{
	CBaseFont *pFont = GetIFontFromHandle( font );
	if( pFont )
		pFont->GetCharABCWidths( ch, a, b, c );
	else
		a = b = c = 0;
}

int CFontManager::GetCharacterWidth(HFont font, int ch)
{
	int a, b, c;
	GetCharABCWide( font, ch, a, b, c );
	return a + b + c;
}

int CFontManager::GetCharacterWidthScaled(HFont font, int ch, int height)
{
	return GetCharacterWidth( font, ch )
#ifdef SCALE_FONTS
		* ((float)height / (float)GetFontTall( font ))
#endif
	;
}

HFont CFontManager::GetFontByName(const char *name)
{
	for( int i = 0; i < m_Fonts.Count(); i++ )
	{
		if( !stricmp( name, m_Fonts[i]->GetName() ) )
			return i;
	}
	return -1;
}

int CFontManager::GetFontTall(HFont font)
{
	CBaseFont *pFont = GetIFontFromHandle( font );
	if( pFont )
		return pFont->GetTall();
	return 0;
}

int CFontManager::GetFontAscent(HFont font)
{
	CBaseFont *pFont = GetIFontFromHandle( font );
	if( pFont )
		return pFont->GetAscent();
	return 0;
}

bool CFontManager::GetFontUnderlined(HFont font)
{
	CBaseFont *pFont = GetIFontFromHandle( font );
	if( pFont )
		return pFont->GetFlags() & FONT_UNDERLINE;
	return false;
}

void CFontManager::GetTextSize(HFont fontHandle, const char *text, int *wide, int *tall, int size )
{
	CBaseFont *font = GetIFontFromHandle( fontHandle );

	if( !font || !text || !text[0] )
	{
		if( wide ) *wide = 0;
		if( tall ) *tall = 0;
		return;
	}

	int fontTall = font->GetHeight(), x = 0;
	int _wide = 0, _tall;
	const char *ch = text;
	_tall = fontTall;
	int i = 0;
	utfstate_t state;

	while( *ch && ( size < 0 || i < size ) )
	{
		// Skip colorcodes
		if( IsColorString( ch ) )
		{
			ch += 2;
			continue;
		}

		int uch = state.Decode((uint8_t)*ch );

		if( uch )
		{
			if( uch == '\n' && *( ch + 1 ) != '\0' )
			{
				_tall += fontTall;
				x = 0;
			}
			else
			{
				int a, b, c;
				font->GetCharABCWidths( uch, a, b, c );
				x += a + b + c;
				if( x > _wide )
					_wide = x;
			}
		}
		i++;
		ch++;
	}

	if( tall ) *tall = _tall;
	if( wide ) *wide = _wide;
}

int CFontManager::CutText(HFont fontHandle, const char *text, int height, int visibleSize, bool reverse, bool stopAtWhitespace, int *wide, bool *remaining )
{
	CBaseFont *font = GetIFontFromHandle( fontHandle );

	if( remaining )
		*remaining = false;

	if( !font || !text || !text[0] || visibleSize <= 0 )
		return 0;

	int _wide = 0;
	const char *ch = text;
	utfstate_t state;

#ifdef SCALE_FONTS
	visibleSize  = (float)visibleSize / (float)height * (float)font->GetTall();
#endif

	int whiteSpacePos = 0;

	// calculate full text wide
	while( *ch )
	{
		// skip colorcodes
		if( IsColorString( ch ) )
		{
			ch += 2;
			continue;
		}

		int uch = state.Decode((uint8_t)*ch );
		int x = 0;
		if( uch )
		{
			if( uch == '\n' )
			{
				ch++;
				break; //
			}

			int a, b, c;
			font->GetCharABCWidths( uch, a, b, c );
			x = a + b + c;

			if( uch == ' ' )
			{
				whiteSpacePos = ch - text;
			}
		}

		if( !reverse && _wide + x >= visibleSize )
			break;

		ch++;
		_wide += x;
	}

	if( !reverse )
	{
		if( *ch && remaining ) *remaining = true;
		if( wide ) *wide = _wide;
		if( stopAtWhitespace && whiteSpacePos )
			return whiteSpacePos;
		return ch - text;
	}

	if( _wide < visibleSize )
	{
		if( remaining ) *remaining = false;
		if( wide ) *wide = _wide;
		return 0;
	}

	ch = text;

	whiteSpacePos = 0;

	// now remove character one by one to fit
	state.Reset();
	while( *ch && _wide > visibleSize )
	{
		// skip colorcodes
		if( IsColorString( ch ) )
		{
			ch += 2;
			continue;
		}

		int uch = state.Decode((uint8_t)*ch );
		if( uch )
		{
			// we don't need check for newlines here, it's only done for oneline Field widget
			int a, b, c;
			font->GetCharABCWidths( uch, a, b, c );
			_wide -= a + b + c;

			if( uch == ' ' )
			{
				whiteSpacePos = ch - text;
			}
		}
		ch++;
	}

	if( remaining ) *remaining = true;
	if( wide ) *wide = _wide;
	if( stopAtWhitespace && whiteSpacePos ) return whiteSpacePos;
	return ch - text;

}

int CFontManager::GetTextWide(HFont font, const char *text, int size)
{
	int wide;

	GetTextSize( font, text, &wide, NULL, size );

	return wide;
}

int CFontManager::GetTextHeight(HFont fontHandle, const char *text, int size )
{
	CBaseFont *font = GetIFontFromHandle( fontHandle );
	if( !font || !text || !text[0] )
	{
		return 0;
	}

	int height = font->GetHeight();

	// lightweight variant only for getting text height
	int i = 0;
	while( *text&&( size < 0 || i < size ) )
	{
		if( *text == '\n' )
			height += height;

		text++;
		i++;
	}
	return height;
}

int CFontManager::GetTextHeightExt( HFont fontHandle, const char *text, int height, int w, int size )
{
	CBaseFont *font = GetIFontFromHandle( fontHandle );
	if( !font || !text || !text[0] || !w )
	{
		return 0;
	}

	const char *text2 = text;
	int y = 0;

	while( *text2 && ( size < 0 || text2 - text < size ) )
	{
		int pos = CutText( fontHandle, text2, height, w, false, true );
		if( pos == 0 )
			break;

		y += height;
		text2 += pos;
	}

	return y;

}

int CFontManager::GetTextWideScaled(HFont font, const char *text, const int height, int size)
{
	CBaseFont *pFont = GetIFontFromHandle( font );
	if( pFont )
	{
		return GetTextWide( font, text, size )
#ifdef SCALE_FONTS
			* ((float)height / (float)pFont->GetTall())
#endif
		;
	}

	return 0;
}

void CFontManager::UploadTextureForFont(CBaseFont *font)
{
	// upload only latin needed for english and cyrillic needed for russian
	// maybe it would be extended someday...

	charRange_t range[] =
	{
	{ 0x0021, 0x007E, NULL, 0 }, // ascii printable range
	{ 0x00C0, 0x00FF, NULL, 0 }, // latin-1 supplement (letters only)
	{ 0x0100, 0x017F, NULL, 0 }, // latin extended a
	{ 0x0400, 0x045F, NULL, 0 }, // cyrillic range
	{ 0, 0, table_cp1251, V_ARRAYSIZE( table_cp1251 ) }, // cp1251
	};

	font->UploadGlyphsForRanges( range, V_ARRAYSIZE( range ) );
}

int CFontManager::DrawCharacter(HFont fontHandle, int ch, Point pt, int charH, const unsigned int color, bool forceAdditive )
{
	CBaseFont *font = GetIFontFromHandle( fontHandle );

	if( !font )
		return 0;

	return font->DrawCharacter( ch, pt, charH, color, forceAdditive );
}

void CFontManager::DebugDraw(HFont fontHandle)
{
	CBaseFont *font = GetIFontFromHandle(fontHandle);

	font->DebugDraw();
}


HFont CFontBuilder::Create()
{
	CBaseFont *font;

	// check existing font at first
	if( !m_hForceHandle )
	{
		for( int i = 0; i < g_FontMgr->m_Fonts.Count(); i++ )
		{
			font = g_FontMgr->m_Fonts[i];

			if( font->IsEqualTo( m_szName, m_iTall, m_iWeight, m_iBlur, m_iFlags ) )
				return i + 1;
		}
	}

#if defined(MAINUI_USE_FREETYPE)
	font = new CFreeTypeFont();
#elif defined(MAINUI_USE_STB)
	font = new CStbFont();
#elif defined(_WIN32) && defined(MAINUI_USE_CUSTOM_FONT_RENDER)
	font = new CWinAPIFont();
#else
	font = new CBitmapFont();
#endif

	double starttime = EngFuncs::DoubleTime();

	if( !font->Create( m_szName, m_iTall, m_iWeight, m_iBlur, m_fBrighten, m_iOutlineSize, m_iScanlineOffset, m_fScanlineScale, m_iFlags ) )
	{
		delete font;

		// fallback to bitmap font
		font = new CBitmapFont();

		// should never fail
		if( !font->Create( "Bitmap Font", m_iTall, m_iWeight, m_iBlur, m_fBrighten, m_iOutlineSize, m_iScanlineOffset, m_fScanlineScale, m_iFlags ) )
		{
			delete font;
			return -1;
		}
	}

	g_FontMgr->UploadTextureForFont( font );

	double endtime = EngFuncs::DoubleTime();

	Con_DPrintf( "Rendering %s(%i, %i) took %f seconds\n", font->GetName(), m_iTall, m_iWeight, endtime - starttime );

	if( m_hForceHandle != -1 && g_FontMgr->m_Fonts.Count() != m_hForceHandle )
	{
		if( g_FontMgr->m_Fonts.IsValidIndex( m_hForceHandle ) )
		{
			g_FontMgr->m_Fonts.FastRemove( m_hForceHandle );
			return g_FontMgr->m_Fonts.InsertBefore( m_hForceHandle, font );
		}
	}

	return g_FontMgr->m_Fonts.AddToTail(font) + 1;
}

bool CFontManager::FindFontDataFile( const char *name, int tall, int weight, int flags, char *dataFile, size_t dataFileChars )
{
	(void)name; (void)tall; (void)weight; (void)flags;

	// Every face (default/small/big/bold/blur/console/banner) resolves to the
	// single system font named in config/fonts.json. The "@system:" prefix
	// tells LoadFontDataFile() to use stdio instead of the VFS, which refuses
	// absolute paths. No TTF/TTC is copied into the game tree.
	FC_Load();

	const size_t prefixLen = strlen( FONT_SYSTEM_PREFIX );
	if( dataFileChars < prefixLen + strlen( s_FontConfig.fullpath ) + 1 )
		return false;

	snprintf( dataFile, dataFileChars, "%s%s", FONT_SYSTEM_PREFIX, s_FontConfig.fullpath );
	return true;
}

byte *CFontManager::LoadFontDataFile( const char *vfspath, int *plen )
{
	const size_t prefixLen = strlen( FONT_SYSTEM_PREFIX );

	// System font: read the OS file directly. Cached on the manager, not in
	// m_FontFiles, because this buffer is new[] and must NOT be released with
	// COM_FreeFile(). One buffer is shared by every face we create.
	if( !strncmp( vfspath, FONT_SYSTEM_PREFIX, prefixLen ))
	{
		const char *path = vfspath + prefixLen;

		if( m_pSystemFontData )
		{
			if( plen ) *plen = m_iSystemFontDataLen;
			return m_pSystemFontData;
		}

		FILE *f = fopen( path, "rb" );
		if( !f )
		{
			Con_Printf( "FontConfig: unable to open system font %s\n", path );
			return NULL;
		}

		fseek( f, 0, SEEK_END );
		long n = ftell( f );
		fseek( f, 0, SEEK_SET );
		if( n <= 0 )
		{
			fclose( f );
			return NULL;
		}

		byte *p = new byte[n];
		size_t got = fread( p, 1, (size_t)n, f );
		fclose( f );
		if( got != (size_t)n )
		{
			delete[] p;
			Con_Printf( "FontConfig: short read on %s\n", path );
			return NULL;
		}

		m_pSystemFontData = p;
		m_iSystemFontDataLen = (int)n;
		if( plen ) *plen = (int)n;
		return p;
	}

	int i = m_FontFiles.Find( vfspath );
	if( i != m_FontFiles.InvalidIndex( ))
	{
		if( plen )
			*plen = m_FontFiles[i].length;

		return m_FontFiles[i].data;
	}
	int len = 0;
	byte *p = EngFuncs::COM_LoadFile( vfspath, &len );
	if( p != nullptr )
	{
		if( plen )
			*plen = len;

		font_file file = { len, p };
		m_FontFiles.Insert( vfspath, file );
	}

	return p;
}
