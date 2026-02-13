import { type NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const returnTo = searchParams.get('return_to');
  
  if (!returnTo) {
    return NextResponse.redirect(new URL('/', request.url));
  }

  try {
    const returnURL = new URL(returnTo);
    
    if (!returnURL.hostname.endsWith('.vercel.app') && returnURL.hostname !== 'localhost') {
      return NextResponse.redirect(new URL('/?error=invalid_redirect', request.url));
    }

    const sessionCookie = request.cookies.get('neon-session')?.value;
    
    if (!sessionCookie) {
      return NextResponse.redirect(new URL('/?error=no_session', returnURL.origin));
    }

    const bridgeURL = new URL('/auth/callback', returnURL);
    bridgeURL.searchParams.set('session', sessionCookie);
    return NextResponse.redirect(bridgeURL);
  } catch (e) {
    console.error('Auth bridge error:', e);
    return NextResponse.redirect(new URL('/?error=bridge_failed', request.url));
  }
}
